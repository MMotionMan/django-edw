# -*- coding: utf-8 -*-
from __future__ import unicode_literals


from django.core import exceptions
from django.core.cache import cache
from django.core.exceptions import ValidationError, ObjectDoesNotExist, MultipleObjectsReturned
from django.db.models.expressions import BaseExpression
from django.db import models
from django.template import TemplateDoesNotExist
from django.template.loader import select_template
from django.utils.six import with_metaclass
from django.utils.html import strip_spaces_between_tags
from django.utils.safestring import mark_safe, SafeText
from django.utils.translation import get_language_from_request
from django.utils.translation import ugettext_lazy as _
from django.utils.functional import cached_property

from django.apps import apps

from rest_framework import serializers
from rest_framework.reverse import reverse
from rest_framework.compat import unicode_to_repr

from rest_framework_bulk.serializers import BulkListSerializer, BulkSerializerMixin

from edw import settings as edw_settings
from edw.models.entity import EntityModel
from edw.models.term import TermModel
from edw.models.data_mart import DataMartModel
from edw.models.related import AdditionalEntityCharacteristicOrMarkModel
from edw.models.rest import (
    DynamicFieldsSerializerMixin,
    DynamicFieldsListSerializerMixin,
    DynamicCreateUpdateValidateSerializerMixin,
    DynamicCreateUpdateValidateListSerializerMixin,
    CheckPermissionsSerializerMixin,
    CheckPermissionsBulkListSerializerMixin,
)
from edw.rest.serializers.data_mart import DataMartCommonSerializer, DataMartDetailSerializer
from edw.rest.serializers.decorators import empty
from edw.utils.set_helpers import uniq


class AttributeSerializer(serializers.Serializer):
    """
    A serializer to convert the characteristics and marks for rendering.
    """
    name = serializers.CharField(read_only=True)
    path = serializers.CharField()
    values = serializers.ListField(child=serializers.CharField())
    view_class = serializers.ListField(child=serializers.CharField(), read_only=True)


class EntityDynamicMetaMixin(object):
    _meta_cache = {}

    @staticmethod
    def _get_meta_class(base, model_class):

        class Meta(base):
            model = model_class

        return Meta

    @classmethod
    def _update_meta(cls, it, model_class):
        key = model_class.__name__
        meta_class = cls._meta_cache.get(key, None)
        if meta_class is None:
            cls._meta_cache[key] = meta_class = EntityDynamicMetaMixin._get_meta_class(it.Meta, model_class)
        setattr(it, 'Meta', meta_class)

    def __new__(cls, *args, **kwargs):
        it = super(EntityDynamicMetaMixin, cls).__new__(cls, *args, **kwargs)
        if args and isinstance(args[0], models.Model):
            cls._update_meta(it, args[0].__class__)
        else:
            data = kwargs.get('data', None)
            if data is not None:
                context = kwargs.get('context', None)
                if context is not None:
                    request = context['request']
                    value = request.GET.get('data_mart_pk', None)
                    if value is not None:
                        # try find data_mart in cache
                        data_mart = request.GET.get('_data_mart', None)
                        if data_mart is not None and isinstance(data_mart, DataMartModel):
                            cls._update_meta(it, data_mart.entities_model)
                        else:
                            key = 'pk'
                            # it was a string, not an int. Try find object by `slug`
                            try:
                                value = int(value)
                            except ValueError:
                                key = 'slug'
                            try:
                                data_mart = DataMartModel.objects.active().get(**{key: value})
                            except DataMartModel.DoesNotExist:
                                pass
                            else:
                                cls._update_meta(it, data_mart.entities_model)
                    else:
                        # в случаи списка пытаемся определить модель по полю 'entity_model' первого элемента
                        if isinstance(data, list):
                            entity_model = data[0].get('entity_model', None) if len(data) else None
                        else:
                            entity_model = data.get('entity_model', None)
                        # пытаемся определить модель по параметру 'entity_model' словаря GET
                        if entity_model is None:
                            entity_model = request.GET.get('entity_model', None)

                        if entity_model is not None:
                            try:
                                model_class = apps.get_model(EntityModel._meta.app_label, str(entity_model))
                            except LookupError:
                                pass
                            else:
                                cls._update_meta(it, model_class)
        return it


class EntityBulkListSerializer(EntityDynamicMetaMixin,
                               CheckPermissionsBulkListSerializerMixin,
                               DynamicFieldsListSerializerMixin,
                               DynamicCreateUpdateValidateListSerializerMixin,
                               BulkListSerializer):

    class Meta:
        model = None

    def __init__(self, *args, **kwargs):
        super(EntityBulkListSerializer, self).__init__(*args, **kwargs)
        # make sure that child model is correct
        if self.Meta.model is not None:
            self.child.Meta.model = self.Meta.model


#==============================================================================
# EntityValidator
#==============================================================================
class EntityValidator(object):
    """
    Entity Validator
    """

    FIELD_REQUIRED_ERROR_MESSAGE = _('This field is required.')

    def set_context(self, serializer):
        """
        This hook is called by the serializer instance,
        prior to the validation call being made.
        """
        self.serializer = serializer

    def __call__(self, attrs):
        model = self.serializer.Meta.model
        # Determine the existing instance, if this is an update operation.
        instance = getattr(self.serializer, 'instance', None)

        validated_data = dict(attrs)

        available_terms_ids = set(self.serializer.data_mart_available_terms_ids)

        attr_errors = {}
        for (attr_name, attribute_mode) in [
            ('characteristics', TermModel.attributes.is_characteristic),
            ('marks', TermModel.attributes.is_mark)
        ]:
            attributes = validated_data.pop(attr_name, None)
            if attributes is not None:
                errors = []
                terms = TermModel.objects.active().attribute_filter(attribute_mode)
                for attribute in attributes:
                    error = {}
                    path = attribute.get('path', None)
                    if path is not None:
                        # Try find Term by `slug` or `path`
                        field = 'slug' if path.find('/') == -1 else 'path'
                        try:
                            terms.get(**{field: path, 'id__in': available_terms_ids})
                        except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
                            error.update({'path': _("{} `{}`='{}'").format(str(e), field, path)})

                    else:
                        error.update({'path': [self.FIELD_REQUIRED_ERROR_MESSAGE]})
                    values = attribute.get('values', None)
                    if values is None:
                        error.update({'values': [self.FIELD_REQUIRED_ERROR_MESSAGE]})
                    errors.append(error)
                if any(errors):
                    attr_errors[attr_name] = errors

        terms_paths = validated_data.pop('terms_paths', None)
        if terms_paths is not None:
            errors = []
            terms = TermModel.objects.active().no_external_tagging_restriction()
            for path in terms_paths:
                # Try find Term by `slug` or `path`
                field = 'slug' if path.find('/') == -1 else 'path'
                try:
                    terms.get(**{field: path, 'id__in': available_terms_ids})
                except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
                    errors.append(_("{} `{}`='{}'").format(str(e), field, path))
            if any(errors):
                attr_errors['terms_paths'] = errors

        terms_ids = validated_data.pop('active_terms_ids', None)
        if terms_ids is not None:
            not_found_ids = list(set(terms_ids) - available_terms_ids)
            if not_found_ids:
                attr_errors['terms_ids'] = _("Terms with id`s [{}] not found.").format(
                    ', '.join(str(x) for x in not_found_ids))

        if attr_errors:
            raise serializers.ValidationError(attr_errors)

        validate_unique = instance is None
        try:
            model(**validated_data).full_clean(validate_unique=validate_unique)
        except ObjectDoesNotExist as e:
            raise exceptions.NotFound(e)
        except ValidationError as e:
            raise serializers.ValidationError(e)

    def __repr__(self):
        return unicode_to_repr('<%s>' % (
            self.__class__.__name__
        ))


#==============================================================================
# EntityCommonSerializer
#==============================================================================
class EntityCommonSerializer(CheckPermissionsSerializerMixin,
                             BulkSerializerMixin,
                             serializers.ModelSerializer):
    """
    Common serializer for the Entity model, both for the EntitySummarySerializer and the
    EntityDetailSerializer.
    """
    entity_model = serializers.CharField(read_only=True)
    entity_name = serializers.CharField(read_only=True)
    active = serializers.BooleanField(required=False)

    class Meta:
        model = EntityModel
        list_serializer_class = EntityBulkListSerializer
        validators = [EntityValidator()]

    HTML_SNIPPET_CACHE_KEY_PATTERN = 'entity:{0}|{1}-{2}-{3}-{4}-{5}'

    def render_html(self, entity, postfix):
        """
        Return a HTML snippet containing a rendered summary for this entity.
        Build a template search path with `postfix` distinction.
        """
        if not self.label:
            msg = "The Entity Serializer must be configured using a `label` field."
            raise exceptions.ImproperlyConfigured(msg)
        app_label = entity._meta.app_label.lower()
        request = self.context['request']
        cache_key = self.HTML_SNIPPET_CACHE_KEY_PATTERN.format(entity.id, app_label, self.label, entity.entity_model,
                                                            postfix, get_language_from_request(request))
        content = cache.get(cache_key)
        if content:
            return mark_safe(content)
        params = [
            (app_label, self.label, entity.entity_model, postfix),
            (app_label, self.label, 'entity', postfix),
            ('edw', self.label, 'entity', postfix),
        ]
        try:
            template = select_template(['{0}/entities/{1}-{2}-{3}.html'.format(*p) for p in params])
        except TemplateDoesNotExist:
            return SafeText("<!-- no such template: `{0}/entities/{1}-{2}-{3}.html` -->".format(*params[0]))
        # when rendering emails, we require an absolute URI, so that media can be accessed from
        # the mail client
        absolute_base_uri = request.build_absolute_uri('/').rstrip('/')
        context = {
            'entity': entity,
            'ABSOLUTE_BASE_URI': absolute_base_uri
        }
        data_mart = self.context.get('data_mart', None)
        if data_mart is not None:
            context['data_mart'] = data_mart
        content = strip_spaces_between_tags(template.render(context, request).strip())
        cache.set(cache_key, content, edw_settings.CACHE_DURATIONS['entity_html_snippet'])
        return mark_safe(content)

    @cached_property
    def group_size_alias(self):
        return self.Meta.model.objects.queryset_class.GROUP_SIZE_ALIAS

    @cached_property
    def data_mart_available_terms_ids(self):
        """
        Return available terms ids for current data mart and filters
        """
        # дерево терминов вычисляется на этапе фильтрации, помимо витрины данных учитываются дополнительные фильтры
        tree = self.context.get('initial_filter_meta', None)
        if tree is None:
            # при POST запросе потребуется вычислить дерево терминов, поскольку фильтрация не производится
            data_mart = self.context['request'].GET['_data_mart']
            if data_mart is not None:
                tree = TermModel.decompress(data_mart.active_terms_ids)
            else:
                return []
        # Удаляем термины с ограничением на установку извне
        return [key for key, value in tree.expand().items() if not value.term.system_flags.external_tagging_restriction]


class SerializerRegistryMetaclass(serializers.SerializerMetaclass):
    """
    Keep a global reference onto the class implementing `EntitySummarySerializerBase`.
    There can be only one class instance, because the entities summary is the lowest common
    denominator for all entities of this edw instance. Otherwise we would be unable to mix
    different polymorphic entity types in the all list views.
    """
    def __new__(cls, clsname, bases, attrs):
        global entity_summary_serializer_class
        if entity_summary_serializer_class:
            msg = "Class `{}` inheriting from `EntitySummarySerializerBase` already registred."
            raise exceptions.ImproperlyConfigured(msg.format(entity_summary_serializer_class.__name__))
        new_class = super(cls, SerializerRegistryMetaclass).__new__(cls, clsname, bases, attrs)
        if clsname != 'EntitySummarySerializerBase':
            entity_summary_serializer_class = new_class
        return new_class

entity_summary_serializer_class = None


#==============================================================================
# EntitySummarySerializerBase
#==============================================================================
class EntitySummarySerializerBase(with_metaclass(SerializerRegistryMetaclass, EntityCommonSerializer)):
    """
    Serialize a summary of the polymorphic Entity model, suitable for Catalog List Views and other Views.
    """
    entity_url = serializers.SerializerMethodField()
    entity_type = serializers.CharField(read_only=True)

    short_characteristics = AttributeSerializer(read_only=True, many=True)
    short_marks = AttributeSerializer(read_only=True, many=True)

    extra = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('label', 'summary')
        # init local cache for calculating attributes
        self.attributes_ancestors_local_cache = {}
        super(EntitySummarySerializerBase, self).__init__(*args, **kwargs)

    def to_representation(self, data):
        """
        Prepare some data for serialization
        """
        # inject local cache to entity
        data.attributes_ancestors_local_cache = self.attributes_ancestors_local_cache
        if self.group_by:
            group_size = getattr(data, self.group_size_alias, 0)
            if group_size > 1:
                queryset = self.context['filter_queryset']
                group_queryset = queryset.alike(data.id, *self.group_by)
                # inject local cache to entities group
                group_queryset.attributes_ancestors_local_cache = self.attributes_ancestors_local_cache
                # patch short_characteristics & short_marks
                data.short_characteristics = group_queryset.short_characteristics
                data.short_marks = group_queryset.short_marks
        else:
            group_size = 0
        self._group_size = group_size
        return super(EntitySummarySerializerBase, self).to_representation(data)

    @cached_property
    def group_by(self):
        return self.context.get('group_by', [])

    @cached_property
    def is_root(self):
        return self == self.root or (
                self.parent and self.parent.parent and isinstance(self.parent.parent, EntityTotalSummarySerializer))

    @cached_property
    def annotation_meta(self):
        # annotation_meta only for root
        if self.is_root:
            return self.context.get('annotation_meta', None)
        return None

    def get_entity_url(self, instance):
        return instance.get_absolute_url(request=self.context.get('request'), format=self.context.get('format'))

    def get_extra(self, instance):
        extra = instance.get_summary_extra(self.context)
        if self._group_size > 1:
            if extra is None:
                extra = {}
            extra[self.group_size_alias] = self._group_size
            extra.update(instance.get_group_extra(self.context))
            return extra

        if self.annotation_meta:
            annotation = {}
            name_field = serializers.CharField()
            for key, (alias, field, name) in self.annotation_meta.items():
                if field == field.root:
                    field.root = self.root
                value = getattr(instance, key, empty)
                if value == empty:
                    value = [getattr(instance, x) for x in alias] if isinstance(
                        alias, (tuple, list)) else getattr(instance, alias)
                if value is None:
                    try:
                        value = field.to_representation(value)
                    except TypeError:
                        value = None
                else:
                    value = field.to_representation(value)
                annotation[key] = value if name is None else {
                    'value': value,
                    'name': name_field.to_representation(name)
                }
            if extra is not None:
                extra.update(annotation)
            else:
                extra = annotation
        return extra


class RelatedDataMartSerializer(DataMartCommonSerializer):
    entities_url = serializers.SerializerMethodField()
    is_subjective = serializers.SerializerMethodField()

    class Meta(DataMartCommonSerializer.Meta):
        fields = ('id', 'parent_id', 'name', 'slug', 'data_mart_url', 'data_mart_model', 'is_leaf',
              'active', 'view_class', 'short_description', 'is_subjective', 'entities_url')

    def get_entities_url(self, instance):
        request = self.context.get('request', None)

        kwargs = {
            'data_mart_pk': instance.id
        }
        if instance.is_subjective:
            kwargs['entity_pk'] = self.entity_pk
            view_name = "edw:data-mart-entity-by-subject-list"
        else:
            view_name = "edw:data-mart-entity-list"

        format = self.context.get('format', None)
        return reverse(view_name, request=request, kwargs=kwargs, format=format)

    @property
    def entity_pk(self):
        return self.context.get('_entity_pk')

    def get_is_subjective(self, instance):
        return instance.is_subjective


#==============================================================================
# EntityDetailSerializerBase
#==============================================================================
class EntityDetailSerializerBase(EntityDynamicMetaMixin,
                                 DynamicFieldsSerializerMixin,
                                 DynamicCreateUpdateValidateSerializerMixin,
                                 EntityCommonSerializer):
    """
    Serialize all fields of the Entity model, for the entities detail view.
    """

    terms_ids = serializers.ListSerializer(child=serializers.IntegerField(), required=False, source='active_terms_ids')
    terms_paths = serializers.ListSerializer(child=serializers.CharField(), required=False, write_only=True)

    characteristics = AttributeSerializer(many=True, required=False)
    marks = AttributeSerializer(many=True, required=False)
    related_data_marts = serializers.SerializerMethodField()

    extra = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('label', 'detail')
        super(EntityDetailSerializerBase, self).__init__(*args, **kwargs)

    def _update_entity(self, instance, validated_data, action='update'):
        attr_terms_ids = []
        for (attr_name, attribute_mode) in [
            ('characteristics', TermModel.attributes.is_characteristic),
            ('marks', TermModel.attributes.is_mark)
        ]:
            attributes = validated_data.pop(attr_name, None)
            if attributes is not None:
                terms = TermModel.objects.active().attribute_filter(attribute_mode)
                for attribute in attributes:
                    path, values = attribute['path'], attribute['values']
                    try:
                        # Try find Term by `slug` or `path`
                        term = terms.get(slug=path) if path.find('/') == -1 else terms.get(path=path)
                    except (ObjectDoesNotExist, MultipleObjectsReturned) as e:
                        raise serializers.ValidationError(str(e))

                    values_terms_map = {x['name']: x['id'] for x in reversed(
                        term.get_descendants(include_self=False).filter(
                            name__in=values).no_external_tagging_restriction().values('id', 'name'))}

                    if values:
                        for value in values:
                            if value in values_terms_map:
                                attr_terms_ids.append(values_terms_map[value])
                                del values_terms_map[value]
                                AdditionalEntityCharacteristicOrMarkModel.objects.filter(
                                    term=term, entity=instance, value=value).delete()
                            else:
                                try:
                                    result, created = AdditionalEntityCharacteristicOrMarkModel.objects.update_or_create(
                                        term=term,
                                        entity=instance,
                                        defaults={
                                            'value': value
                                        }
                                    )
                                except MultipleObjectsReturned as e:
                                    raise serializers.ValidationError(str(e))
                    else:
                        AdditionalEntityCharacteristicOrMarkModel.objects.filter(term=term, entity=instance).delete()


        terms_paths = validated_data.pop('terms_paths', None)
        if terms_paths is not None:
            terms = TermModel.objects.active().no_external_tagging_restriction()
            query_attrs = {
                'path': [],
                'slug': []
            }
            for path in terms_paths:
                # Try find Term by `slug` or `path`
                query_attrs['slug' if path.find('/') == -1 else 'path'].append(path)
            for key, values in query_attrs.items():
                if values:
                    attr_terms_ids.extend(terms.filter(**{"{}__in".format(key): values}).values_list('id', flat=True))

        terms_ids = validated_data.pop('active_terms_ids', None)
        if terms_ids is not None or attr_terms_ids:
            attr_terms_ids = list(set(attr_terms_ids) & set(self.data_mart_available_terms_ids))
            if terms_ids is None:
                terms_ids = attr_terms_ids
            else:
                terms_ids.extend(attr_terms_ids)
            data_mart = self.context.get(
                'data_mart', None) if action == 'update' else self.context['request'].GET.get('_data_mart', None)
            if data_mart is not None:
                terms_ids.extend(data_mart.active_terms_ids)
                instance.terms = uniq(terms_ids)

    def create(self, validated_data):
        origin_validated_data = validated_data.copy()
        for key in ('active_terms_ids', 'terms_paths', 'characteristics', 'marks'):
            validated_data.pop(key, None)

        model = self.Meta.model
        for id_attr in model._rest_meta.lookup_fields:
            id_value = validated_data.pop(id_attr, empty)
            if id_value != empty:
                try:
                    instance, created = model.objects.update_or_create(**{
                        id_attr: id_value,
                        'defaults': validated_data
                    })
                except MultipleObjectsReturned as e:
                    raise serializers.ValidationError(e)
                break
        else:
            raise serializers.ValidationError(
                _("Lookup fields not found [{}]").format(", ".join(model._rest_meta.lookup_fields)))

        self._update_entity(instance, origin_validated_data, action='create')

        # print (">>> create <<<", instance)
        return instance

    def update(self, instance, validated_data):
        self._update_entity(instance, validated_data)
        result = super(EntityDetailSerializerBase, self).update(instance, validated_data)

        # print (">>> post update <<<", result)
        return result

    @cached_property
    def is_root(self):
        return self == self.root

    @cached_property
    def group_by(self):
        # group only for root
        if self.is_root:
            return self.context.get('group_by', [])
        return []

    def get_related_data_marts(self, entity):
        ids = entity.get_related_data_marts_ids_from_attributes(entity.marks, entity.characteristics)
        data_marts0 = entity.related_data_marts.active() # todo: необходимо найти все связанные с группой витрины данных

        if ids:
            data_marts0 = list(data_marts0)
            data_marts1 = list(DataMartModel.objects.active().filter(id__in=ids))

            data_marts = []
            while data_marts0 and data_marts1:
                if data_marts0[0] == data_marts1[0]:
                    data_marts.append(data_marts1.pop(0))
                    data_marts0.pop(0)
                elif data_marts0[0] < data_marts1[0]:
                    data_marts.append(data_marts0.pop(0))
                else:
                    data_marts.append(data_marts1.pop(0))
            if data_marts0:
                data_marts.extend(data_marts0)
            elif data_marts1:
                data_marts.extend(data_marts1)
        else:
            data_marts = data_marts0

        related_data_mart_serializer = RelatedDataMartSerializer(data_marts, context=self.context, many=True)
        return related_data_mart_serializer.data

    def get_extra(self, instance):
        extra = self.context.get('extra', None)

        if self._group_size > 1:
            if extra is None:
                extra = {}
            extra[self.group_size_alias] = self._group_size
            extra.update(instance.get_group_extra(self.context))

        return extra

    def to_representation(self, data):
        """
        Prepare some data for serialization
        """
        if self.group_by:
            queryset = self.context['filter_queryset']
            group_queryset = queryset.alike(data.id, *self.group_by)
            group_size = group_queryset.count()
            if group_size > 1:
                # patch characteristics & marks
                data.characteristics = group_queryset.characteristics
                data.marks = group_queryset.marks
        else:
            group_size = 0
        self._group_size = group_size

        self.context['_entity_pk'] = data.id
        return super(EntityDetailSerializerBase, self).to_representation(data)


class EntitySummarySerializer(EntitySummarySerializerBase):
    media = serializers.SerializerMethodField()

    class Meta(EntityCommonSerializer.Meta):
        fields = ('id', 'entity_name', 'entity_url', 'entity_model',
                  'short_characteristics', 'short_marks', 'media', 'extra')

    def get_media(self, entity):
        return self.render_html(entity, 'media')


class EntityDetailSerializer(EntityDetailSerializerBase):
    media = serializers.SerializerMethodField()

    class Meta(EntityCommonSerializer.Meta):
        exclude = ('polymorphic_ctype', 'additional_characteristics_or_marks', '_relations', 'terms')

    def get_media(self, entity):
        return self.render_html(entity, 'media')


class EntitySummaryMetadataSerializer(serializers.Serializer):
    data_mart = serializers.SerializerMethodField()
    terms_ids = serializers.SerializerMethodField()
    subj_ids = serializers.SerializerMethodField()
    ordering = serializers.SerializerMethodField()
    view_component = serializers.SerializerMethodField()
    aggregation = serializers.SerializerMethodField()
    group_by = serializers.SerializerMethodField()
    alike = serializers.SerializerMethodField()
    potential_terms_ids = serializers.SerializerMethodField()
    real_terms_ids = serializers.SerializerMethodField()
    extra = serializers.SerializerMethodField()

    @staticmethod
    def on_terms_ids_cache_set(key):
        buf = EntityModel.get_terms_cache_buffer()
        old_key = buf.record(key)
        if old_key != buf.empty:
            cache.delete(old_key)

    def get_potential_terms_ids(self, instance):
        tree = self.context['initial_filter_meta']
        initial_queryset = self.context['initial_queryset']
        return initial_queryset.get_terms_ids(tree).cache(on_cache_set=self.on_terms_ids_cache_set,
                                                          timeout=EntityModel.TERMS_IDS_CACHE_TIMEOUT)

    def _get_cached_real_terms_ids(self, instance):
        real_terms_ids = getattr(self, '_cached_real_terms_ids', None)
        if real_terms_ids is None:
            tree = self.context['terms_filter_meta']
            filter_queryset = self.context['filter_queryset']
            real_terms_ids = self._cached_real_terms_ids = filter_queryset.get_terms_ids(tree).cache(
                on_cache_set=self.on_terms_ids_cache_set, timeout=EntityModel.TERMS_IDS_CACHE_TIMEOUT)
        return real_terms_ids

    def get_terms_ids(self, instance):
        return self.context['terms_ids']

    def get_real_terms_ids(self, instance):
        return self._get_cached_real_terms_ids(instance)

    def get_data_mart(self, instance):
        data_mart = self.context['data_mart']
        self.context.update({
            'real_terms_ids': self._get_cached_real_terms_ids(instance)
        })
        if data_mart is not None:
            serializer = DataMartDetailSerializer(data_mart, context=self.context)
            return serializer.data
        return None

    def get_subj_ids(self, instance):
        return self.context['subj_ids']

    def get_ordering(self, instance):
        ordering = self.context['ordering']
        return ",".join(ordering) if ordering else None

    def get_view_component(self, instance):
        return self.context['view_component']

    def get_extra(self, instance):
        return self.context.get('extra', None)

    def get_aggregation(self, instance):
        aggregation_meta = self.context['aggregation_meta']
        if aggregation_meta:
            aggregate_kwargs = dict([(key, value[0]) for key, value in aggregation_meta.items()
                                     if isinstance(value[0], BaseExpression)])
            queryset = self.context['filter_queryset']
            aggregation = queryset.aggregate(**aggregate_kwargs)
            result = {}
            name_field = serializers.CharField()
            for key, (alias, field, name) in aggregation_meta.items():
                if field is not None:
                    if field == field.root:
                        field.root = self.root
                    value = aggregation.get(key, empty)
                    if value == empty:
                        value = [aggregation[x] for x in alias] if isinstance(alias, (tuple, list)
                                                                              ) else aggregation[alias]
                    if value is None:
                        try:
                            value = field.to_representation(value)
                        except TypeError:
                            value = None
                    else:
                        value = field.to_representation(value)
                    result[key] = {
                        'value': value,
                        'name': name_field.to_representation(name) if name is not None else None
                    }
            return result
        else:
            return None

    def get_group_by(self, instance):
        return self.context['group_by']

    def get_alike(self, instance):
        alike_id = self.context['alike']
        if alike_id is not None:
            result = {
                'id': alike_id
            }
            queryset = self.context['filter_queryset']
            try:
                obj = queryset.get(id=alike_id)
            except queryset.model.DoesNotExist:
                pass
            else:
                result.update(obj.get_group_extra(self.context))
            return result
        else:
            return None


class EntityTotalSummarySerializer(serializers.Serializer):
    meta = EntitySummaryMetadataSerializer(source="*")
    objects = EntitySummarySerializer(source="*", many=True)

    def __new__(cls, *args, **kwargs):
        kwargs['many'] = False
        return super(EntityTotalSummarySerializer, cls).__new__(cls, *args, **kwargs)
