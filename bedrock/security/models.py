# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from django.db import models
from django.template.defaultfilters import slugify
from django.utils.functional import total_ordering

from django_extensions.db.fields import ModificationDateTimeField
from django_extensions.db.fields.json import JSONField
from bedrock.base.urlresolvers import reverse
from product_details.version_compare import Version


@total_ordering
class Product(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.CharField(max_length=50, db_index=True)
    product = models.CharField(max_length=50)
    product_slug = models.SlugField()

    class Meta:
        ordering = ('slug',)

    def __unicode__(self):
        return self.name

    @property
    def name_and_version(self):
        return self.name.rsplit(None, 1)

    @property
    def name_tuple(self):
        product, vers = self.name_and_version
        if '.' not in vers:
            vers += '.0'
        return product, Version(vers)

    @property
    def html_id(self):
        """Conform to the IDs from the old page so old URL anchors work."""
        return self.slug.replace('-', '')

    @property
    def version(self):
        return self.name_tuple[1]

    def __lt__(self, other):
        return self.name_tuple < other.name_tuple

    def get_absolute_url(self):
        product, vers = self.name_and_version
        return reverse('security.product-version-advisories',
                       kwargs={'product': product, 'version': vers})

    def save(self, force_insert=False, force_update=False,
             using=None, update_fields=None):
        # do not use self.name_tuple because don't want ".0" on versions.
        product, vers = self.name_and_version
        self.product = product
        self.product_slug = slugify(product)
        self.slug = '{0}-{1}'.format(self.product_slug, vers)
        super(Product, self).save(force_insert, force_update,
                                  using, update_fields)


class SecurityAdvisory(models.Model):
    id = models.CharField(max_length=8, primary_key=True, db_index=True)
    title = models.CharField(max_length=200)
    impact = models.CharField(max_length=100, blank=True)
    reporter = models.CharField(max_length=100, blank=True)
    announced = models.DateField(null=True)
    year = models.SmallIntegerField()
    order = models.SmallIntegerField()
    fixed_in = models.ManyToManyField(Product, related_name='advisories')
    extra_data = JSONField()
    html = models.TextField()
    last_modified = ModificationDateTimeField()

    class Meta:
        ordering = ('-year', '-order')
        get_latest_by = 'last_modified'

    def __unicode__(self):
        return u'MFSA {0}'.format(self.id)

    def get_absolute_url(self):
        return reverse('security.advisory', kwargs={'pk': self.id})

    @property
    def impact_class(self):
        if self.impact:
            return self.impact.lower().split(None, 1)[0]
        else:
            return 'none'

    @property
    def products(self):
        prods_set = set(v.product for v in self.fixed_in.all())
        return sorted(prods_set)


class MitreCVE(models.Model):
    id = models.CharField(max_length=15, primary_key=True, db_index=True)
    year = models.SmallIntegerField()
    order = models.SmallIntegerField()
    title = models.CharField(max_length=200, blank=True)
    impact = models.CharField(max_length=100, blank=True)
    reporter = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    products = JSONField(default='[]')
    bugs = JSONField(default='[]')

    class Meta:
        ordering = ('-year', '-order')

    def product_versions(self):
        """Return a list of version numbers per product"""
        prod_vers = {}
        for prod in self.products:
            prod_name, version = prod.rsplit(None, 1)
            if prod_name in prod_vers:
                prod_vers[prod_name].append(version)
            else:
                prod_vers[prod_name] = [version]

        return prod_vers

    def feed_entry(self):
        """Return a MITRE format data structure for the CVE

        See https://github.com/CVEProject/automation-working-group/blob/master/cve_json_schema/DRAFT-JSON-file-format-v4.md
        """
        product_data = []
        for prod_name, versions in self.product_versions().iteritems():
            product_data.append({
                'product_name': prod_name,
                'version': {
                    'version_data': [{'version_value': vers} for vers in versions],
                }
            })

        return {
            'data_type': 'CVE',
            'data_format': 'MITRE',
            'data_version': '4.0',
            'CVE_data_meta': {
                'ID': self.id,
                'ASSIGNER': 'cve@mitre.org'
            },
            'affects': {
                'vendor': {
                    'vendor_data': [
                        {
                            'vendor_name': 'Mozilla',
                            'product': {
                                'product_data': product_data,
                            }
                        }
                    ]
                }
            },
            'problemtype': {
                'problemtype_data': [
                    {
                        'description': [
                            {
                                'lang': 'eng',
                                'value': self.title,
                            }
                        ]
                    }
                ]
            },
            'references': {
                'reference_data': [{'url': bug['url']} for bug in self.bugs],
            },
            'description': {
                'description_data': [
                    {
                        'lang': 'eng',
                        'value': self.description,
                    }
                ]
            }
        }
