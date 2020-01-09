# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import transaction
from django.utils.encoding import force_text
from django.db.models import Q
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _

from edw.models.entity import EntityModel
from edw.models.email_category import get_email_category
from edw.models.term import TermModel


# from edw.signals.place import zone_changed
# from edw.utils.geo import get_location_from_geocoder, get_postcode, GeocoderException


# todo: Разгламурить

class CustomerCategoryMixin(object):
    """
    RUS: Добавляет в модель категорию пользователя которая определяется по его почтовому адресу,
    возможна ручная установка.
    """

    REQUIRED_FIELDS = ('customer',)

    CUSTOMER_CATEGORY_ROOT_TERM_SLUG = "customer-category"
    UNKNOWN_CUSTOMER_TERM_SLUG = "unknown-customer"

    @classmethod
    def validate_term_model(cls):
        """
        RUS: Добавляет термин 'Категория пользователя' и 'Неизвестный пользователь' в модель терминов TermModel
        при их отсутствии.
        """
        # валидируем только один раз
        key = 'vldt:сstmr_ctgr'
        need_validation = EntityModel._validate_term_model_cache.get(key, True)
        if need_validation:
            EntityModel._validate_term_model_cache[key] = False

            with transaction.atomic():
                try:  # customer-category
                    customer_category = TermModel.objects.get(slug=cls.CUSTOMER_CATEGORY_ROOT_TERM_SLUG, parent=None)
                except TermModel.DoesNotExist:
                    customer_category = TermModel(
                        slug=cls.CUSTOMER_CATEGORY_ROOT_TERM_SLUG,
                        parent=None,
                        name=force_text(_('Customer category')),
                        semantic_rule=TermModel.XOR_RULE,
                        system_flags=(TermModel.system_flags.delete_restriction |
                                      TermModel.system_flags.change_parent_restriction |
                                      TermModel.system_flags.change_slug_restriction))
                    customer_category.save()
            with transaction.atomic():
                try:  # unknown-customer
                    customer_category.get_descendants(include_self=False).get(slug=cls.UNKNOWN_CUSTOMER_TERM_SLUG)
                except TermModel.DoesNotExist:
                    unknown_customer = TermModel(
                        slug=cls.UNKNOWN_CUSTOMER_TERM_SLUG,
                        parent_id=customer_category.id,
                        name=force_text(_('Unknown customer')),
                        semantic_rule=TermModel.OR_RULE,
                        system_flags=(TermModel.system_flags.delete_restriction |
                                      TermModel.system_flags.change_parent_restriction |
                                      TermModel.system_flags.change_slug_restriction |
                                      TermModel.system_flags.has_child_restriction))
                    unknown_customer.save()
        super(CustomerCategoryMixin, cls).validate_term_model()

    @staticmethod
    def customer_category_root_term():
        """
        RUS: Ищет корневой термин категории пользователей в модели TermModel (slug = "customer-category").
        Результат кешируется.
        """
        customer_category_root = getattr(EntityModel, "_customer_category_root_term_cache", None)
        if customer_category_root is None:
            try:
                customer_category_root = TermModel.objects.get(
                    slug=CustomerCategoryMixin.CUSTOMER_CATEGORY_ROOT_TERM_SLUG, parent=None)
            except TermModel.DoesNotExist:
                pass
            else:
                EntityModel._customer_category_root_term_cache = customer_category_root
        return customer_category_root

    # @staticmethod
    # def get_region_term():
    #     """
    #     RUS: Ищет регион в модели TermModel с применением PlaceMixin (слаг = "region").
    #     Результат кешируется.
    #     """
    #     region = getattr(EntityModel, "_region_term_cache", None)
    #     if region is None:
    #         try:
    #             region = TermModel.objects.get(slug=PlaceMixin.REGION_ROOT_TERM_SLUG, parent=None)
    #         except TermModel.DoesNotExist:
    #             pass
    #         else:
    #             EntityModel._region_term_cache = region
    #     return region


    @staticmethod
    def get_unknown_customer_term():
        """
        RUS: Ищет термин - неизвестная категория пользователей в модели TermModel (slug = "unknown-customer").
        Результат кешируется.
        """
        unknown_customer = getattr(EntityModel, "_unknown_customer_term_cache", None)
        if unknown_customer is None:
            customer_category_root = CustomerCategoryMixin.customer_category_root_term()
            if unknown_customer is not None:
                try:
                    unknown_customer = customer_category_root.get_descendants(include_self=False).get(
                        slug=CustomerCategoryMixin.UNKNOWN_CUSTOMER_TERM_SLUG)
                except TermModel.DoesNotExist:
                    pass
                else:
                    EntityModel._unknown_customer_term_cache = unknown_customer
        return unknown_customer


    # @staticmethod
    # def get_terra_incognita_term():
    #     """
    #     RUS: добавляет Другие регионы в модель EntityModel, если они отсутствуют.
    #     """
    #     terra_incognita = getattr(EntityModel, "_terra_incognita_cache", None)
    #     if terra_incognita is None:
    #         region = PlaceMixin.get_region_term()
    #         if region is not None:
    #             try:
    #                 terra_incognita = region.get_descendants(include_self=False).get(
    #                     slug=PlaceMixin.TERRA_INCOGNITA_TERM_SLUG)
    #             except TermModel.DoesNotExist:
    #                 #todo: может вернуть none
    #                 pass
    #             else:
    #                 EntityModel._terra_incognita_cache = terra_incognita
    #     return terra_incognita


    @classmethod
    def get_all_customer_categories_terms_ids_set(cls):
        """
        RUS: Добавляет список ids терминов категорий пользователей.
        """
        customer_category_root = CustomerCategoryMixin.customer_category_root_term()
        if customer_category_root is not None:



            ids = customer_category_root.get_descendants(include_self=True).values_list('id', flat=True)

            print ("#### get_all_customer_categories_terms_ids_set", ids)
        else:
            ids = []



        return set(ids)


    # @classmethod
    # def get_all_regions_terms_ids_set(cls):
    #     """
    #     RUS: Добавляет список ids регионов, если есть термин Регион в модели.
    #     """
    #     region = PlaceMixin.get_region_term()
    #     if region is not None:
    #         ids = region.get_descendants(include_self=True).values_list('id', flat=True)
    #     else:
    #         ids = []
    #     return set(ids)

    @cached_property
    def all_customer_categories_terms_ids_set(self):
        """
        RUS: Кэширует список ids категорий терминов.
        """
        return self.get_all_customer_categories_terms_ids_set()

    # @cached_property
    # def all_regions_terms_ids_set(self):
    #     """
    #     RUS: Кэширует список ids регионов.
    #     """
    #     return self.get_all_regions_terms_ids_set()


    def need_terms_validation_after_save(self, origin, **kwargs):
        """
        RUS: Термины зависят от модели CustomerModel, валидируем при создании либо валидация вызывается сигналом.
        """
        
        print ("+++ need_terms_validation_after_save +++", origin.customer_id , self.customer_id)



        if origin is None or origin.customer_id != self.customer_id:
            do_validate = kwargs["context"]["validate_customer_category"] = True
        else:

            tmp1 = EntityModel.terms.through.objects.filter(
                Q(entity_id=self.id) &
                Q(term_id__in=self.all_customer_categories_terms_ids_set)
            ).values_list('term_id', flat=True)

            print ("%%%% SELF TERMS $$$$$", tmp1)

            # todo: here!!!

            do_validate = kwargs["context"]["validate_customer_category"] = True

            # do_validate = kwargs["context"].get("validate_customer_category", True)
            # do_validate = kwargs["context"].get("validate_customer_category", False)
        return super(CustomerCategoryMixin, self).need_terms_validation_after_save(origin, **kwargs) or do_validate


    # def need_terms_validation_after_save(self, origin, **kwargs):
    #     """
    #     RUS: Проставляет автоматически термины, связанные с местоположением объекта,
    #     после сохранения его геопозиции.
    #     """
    #     if (origin is None or origin.geoposition != self.geoposition) and self.geoposition:
    #         do_validate = kwargs["context"]["validate_place"] = True
    #     else:
    #         do_validate = False
    #     return super(PlaceMixin, self).need_terms_validation_after_save(origin, **kwargs) or do_validate
    #
    # def get_location(self):
    #     """
    #     RUS: Определяет местоположение объекта.
    #     """
    #     return get_location_from_geocoder(geoposition=self.geoposition)
    #
    # @cached_property
    # def location(self):
    #     """
    #     RUS: Кэширует местоположение объекта.
    #     """
    #     return self.get_location()

    def get_customer_category_term(self):
        email_category = get_email_category(self.customer.email)
        return email_category.term if email_category else None

    @cached_property
    def customer_category_term(self):
        return self.get_customer_category_term()

    def validate_terms(self, origin, **kwargs):
        """
        RUS: Добавляет id категории пользоватя
        """
        context = kwargs["context"]

        print (">>>>>> !!! validate_terms", self, kwargs)


        print ("%%%%%%% instance._clean_terms %%%%%%", getattr(self, "_clean_terms", None))

        if context.get("force_validate_terms", False) or context.get("validate_customer_category", False):



            if origin is not None:
                to_remove = EntityModel.terms.through.objects.filter(
                    Q(entity_id=self.id) &
                    Q(term_id__in=self.all_customer_categories_terms_ids_set)
                ).values_list('term_id', flat=True)


                print ("*** to_remove ***", to_remove)
                # self.terms.remove(*to_remove)

            else:
                to_remove = []

            if self.customer_category_term:
                if to_remove:
                    self.terms.remove(*to_remove)

                print ("- REMOVE", to_remove)
                print ("+ ADD", self.customer_category_term.id)

                self.terms.add(self.customer_category_term.id)
            else:
                if not to_remove:
                    print ("+ ADD", self.get_unknown_customer_term().id)

                    self.term.add(self.get_unknown_customer_term().id)

            print ("#### customer_category_term ####", self.customer_category_term)


        super(CustomerCategoryMixin, self).validate_terms(origin, **kwargs)

    # def validate_terms(self, origin, **kwargs):
    #     """
    #     RUS: Добавляет id почтовой зоны в случае определения местположения,
    #     если местоположение не определяется, то id добавляется в другие регионы.
    #     """
    #     context = kwargs["context"]
    #     if (context.get("force_validate_terms", False) and not context.get("bulk_force_validate_terms", False)
    #     ) or context.get("validate_place", False):
    #         # нельзя использовать в массовых операциях из ограничения API геокодера
    #         if origin is not None:
    #             to_remove = EntityModel.terms.through.objects.filter(
    #                 Q(entity_id=self.id) &
    #                 Q(term_id__in=self.all_regions_terms_ids_set)
    #             ).values_list('term_id', flat=True)
    #             self.terms.remove(*to_remove)
    #         else:
    #             to_remove = []
    #
    #         try:
    #             postcode = get_postcode(self.location)
    #         except GeocoderException:
    #             zone = None
    #         else:
    #             zone = get_postal_zone(postcode)
    #
    #         if zone is not None:
    #             to_add = [zone.term.id]
    #         else:
    #             to_add = [self.get_terra_incognita_term().id]
    #         self.terms.add(*to_add)
    #
    #         if set(to_add) != set(to_remove):
    #             zone_changed.send(sender=self.__class__, instance=self,
    #                               zone_term_ids_to_remove=to_remove,
    #                               zone_term_ids_to_add=to_add)
    #
    #     super(PlaceMixin, self).validate_terms(origin, **kwargs)
