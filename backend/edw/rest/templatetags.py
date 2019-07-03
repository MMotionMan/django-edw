# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.utils.functional import cached_property
from django.db.models.query import QuerySet
from django.http import QueryDict

from classytags.core import Tag

from rest_framework import request
from rest_framework import exceptions
from rest_framework.generics import get_object_or_404
from rest_framework.settings import api_settings
from rest_framework.renderers import JSONRenderer


def _get_count(queryset):
    """
    Determine an object count, supporting either querysets or regular lists.
    """
    try:
        return queryset.count()
    except (AttributeError, TypeError):
        return len(queryset)


class Request(request.Request):

    def __init__(self, request, query_params=None, *args, **kwargs):
        self._query_params = query_params
        super(Request, self).__init__(request, *args, **kwargs)

    @cached_property
    def query_params(self):
        """
        More semantically correct name for request.GET.
        """
        return self._query_params if self._query_params is not None else self._request.GET

    @property
    def GET(self):
        return self.query_params


class BaseRetrieveDataTag(Tag):
    queryset = None
    serializer_class = None
    action = None

    lookup_field = 'pk'
    lookup_url_kwarg = None

    # The filter backend classes to use for queryset filtering
    filter_backends = api_settings.DEFAULT_FILTER_BACKENDS

    # The style to use for queryset pagination.
    pagination_class = api_settings.DEFAULT_PAGINATION_CLASS

    permission_classes = api_settings.DEFAULT_PERMISSION_CLASSES

    disallow_kwargs = ['varname']

    def permission_denied(self, request, message=None):
        """
        If request is not permitted, determine what kind of exception to raise.
        """
        if not request.successful_authenticator:
            raise exceptions.NotAuthenticated()
        raise exceptions.PermissionDenied(detail=message)

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        return [permission() for permission in self.permission_classes]

    def check_object_permissions(self, request, obj):
        """
        Check if the request should be permitted for a given object.
        Raises an appropriate exception if the request is not permitted.
        """
        permissions = [permission() for permission in obj._rest_meta.permission_classes]
        if not permissions:
            permissions = self.get_permissions()

        for permission in permissions:
            if not permission.has_object_permission(request, self, obj):
                self.permission_denied(
                    request, message=getattr(permission, 'message', None)
                )

    def initialize(self, origin_request, tag_kwargs):
        request = Request(origin_request, query_params=QueryDict('', mutable=True))

        initial_kwargs = tag_kwargs.copy()

        inner_kwargs = initial_kwargs.pop('kwargs', None)

        if inner_kwargs is not None:
            # удаляем пустые параметры
            for k, v in inner_kwargs.items():
                if v == '':
                    del inner_kwargs[k]
            initial_kwargs.update(inner_kwargs)
        self.format_kwarg = initial_kwargs.pop(
            api_settings.FORMAT_SUFFIX_KWARG, None) if api_settings.FORMAT_SUFFIX_KWARG else None
        self.indent = initial_kwargs.pop('indent', None)

        for key in self.disallow_kwargs:
            initial_kwargs.pop(key, None)

        request.query_params.update(initial_kwargs)
        self.initial_kwargs = initial_kwargs

        self.request = request

    def render(self, context):
        items = self.kwargs.items()
        kwargs = dict([(key, value.resolve(context)) for key, value in items])
        kwargs.update(self.blocks)

        request = context.get('request', None)
        assert request is not None, (
            "'%s' `.render()` method parameter `context` should include a `request` attribute."
            % self.__class__.__name__
        )
        self.initialize(request, kwargs)

        return self.render_tag(context, **kwargs)

    def get_queryset(self):
        """
        Get the list of items for this Tag.
        This must be an iterable, and may be a queryset.
        Defaults to using `self.queryset`.
        """
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method."
            % self.__class__.__name__
        )

        queryset = self.queryset
        if isinstance(queryset, QuerySet):
            # Ensure queryset is re-evaluated on each request.
            queryset = queryset.all()
        return queryset

    def get_serializer(self, *args, **kwargs):
        """
        Return the serializer instance.
        """
        serializer_class = self.get_serializer_class()
        kwargs['context'] = self.get_serializer_context()
        return serializer_class(*args, **kwargs)

    def get_serializer_class(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        """
        assert self.serializer_class is not None, (
            "'%s' should either include a `serializer_class` attribute, "
            "or override the `get_serializer_class()` method."
            % self.__class__.__name__
        )

        return self.serializer_class

    def get_serializer_context(self):
        """
        Extra context provided to the serializer class.
        """
        return {
            'request': self.request,
            'format': self.format_kwarg,
            'view': self
        }

    def filter_queryset(self, queryset):
        """
        Given a queryset, filter it with whichever filter backend is in use.
        """
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(self.request, queryset, self)
        return queryset

    def get_object(self):
        """
        Returns the object.
        """
        queryset = self.filter_queryset(self.get_queryset())

        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        filter_kwargs = {self.lookup_field: self.initial_kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj

    @property
    def paginator(self):
        """
        The paginator instance associated with the templatetag, or `None`.
        """
        if not hasattr(self, '_paginator'):
            if self.pagination_class is None:
                self._paginator = None
            else:
                self._paginator = self.pagination_class()
        return self._paginator

    def paginate_queryset(self, queryset):
        """
        Return a single page of results, or `None` if pagination is disabled.
        """
        if self.paginator is None:
            return None

        self._queryset_count = _get_count(queryset)
        page = self.paginator.paginate_queryset(queryset, self.request, view=self)
        self._page_len = len(page)
        return page

    def get_paginated_data(self, data):
        """
        Return a paginated style data object for the given output data.
        """
        assert self.paginator is not None

        return {
            "count": self._queryset_count,
            "is_paginated": self._page_len < self._queryset_count,
            "results": data
        }

    def to_json(self, data):
        return JSONRenderer().render(data, renderer_context={'indent': self.indent})