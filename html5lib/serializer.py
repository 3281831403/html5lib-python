from __future__ import absolute_import, division, unicode_literals
from six import text_type

import re

from codecs import register_error, xmlcharrefreplace_errors

from .constants import voidElements, booleanAttributes, spaceCharacters
from .constants import rcdataElements, entities, xmlEntities
from .constants import namespaces, getNamespacePrefixes
from . import treewalkers, _utils
from xml.sax.saxutils import escape

_quoteAttributeSpecChars = "".join(spaceCharacters) + "\"'=<>`"
_quoteAttributeSpec = re.compile("[" + _quoteAttributeSpecChars + "]")
_quoteAttributeLegacy = re.compile("[" + _quoteAttributeSpecChars +
                                   "\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n"
                                   "\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15"
                                   "\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f"
                                   "\x20\x2f\x60\xa0\u1680\u180e\u180f\u2000"
                                   "\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
                                   "\u2008\u2009\u200a\u2028\u2029\u202f\u205f"
                                   "\u3000]")


_encode_entity_map = {}
_is_ucs4 = len("\U0010FFFF") == 1
for k, v in list(entities.items()):
    # skip multi-character entities
    if ((_is_ucs4 and len(v) > 1) or
            (not _is_ucs4 and len(v) > 2)):
        continue
    if v != "&":
        if len(v) == 2:
            v = _utils.surrogatePairToCodepoint(v)
        else:
            v = ord(v)
        if v not in _encode_entity_map or k.islower():
            # prefer &lt; over &LT; and similarly for &amp;, &gt;, etc.
            _encode_entity_map[v] = k


def htmlentityreplace_errors(exc):
    if isinstance(exc, (UnicodeEncodeError, UnicodeTranslateError)):
        res = []
        codepoints = []
        skip = False
        for i, c in enumerate(exc.object[exc.start:exc.end]):
            if skip:
                skip = False
                continue
            index = i + exc.start
            if _utils.isSurrogatePair(exc.object[index:min([exc.end, index + 2])]):
                codepoint = _utils.surrogatePairToCodepoint(exc.object[index:index + 2])
                skip = True
            else:
                codepoint = ord(c)
            codepoints.append(codepoint)
        for cp in codepoints:
            e = _encode_entity_map.get(cp)
            if e:
                res.append("&")
                res.append(e)
                if not e.endswith(";"):
                    res.append(";")
            else:
                res.append("&#x%s;" % (hex(cp)[2:]))
        return ("".join(res), exc.end)
    else:
        return xmlcharrefreplace_errors(exc)


register_error("htmlentityreplace", htmlentityreplace_errors)


def serialize(input, tree="etree", encoding=None, **serializer_opts):
    """Serializes the input token stream using the specified treewalker

    :arg input: the token stream to serialize

    :arg tree: the treewalker to use

    :arg encoding: the encoding to use

    :arg serializer_opts: any options to pass to the
        :py:class:`html5lib.serializer.HTMLSerializer` that gets created

    :returns: the tree serialized as a string

    Example:

    >>> from html5lib.html5parser import parse
    >>> from html5lib.serializer import serialize
    >>> token_stream = parse('<html><body><p>Hi!</p></body></html>')
    >>> serialize(token_stream, omit_optional_tags=False)
    '<html><head></head><body><p>Hi!</p></body></html>'

    """
    # XXX: Should we cache this?
    walker = treewalkers.getTreeWalker(tree)
    s = HTMLSerializer(**serializer_opts)
    return s.render(walker(input), encoding)


class HTMLSerializer(object):

    # attribute quoting options
    quote_attr_values = "legacy"  # be secure by default
    quote_char = '"'
    use_best_quote_char = True

    # tag syntax options
    omit_optional_tags = True
    minimize_boolean_attributes = True
    use_trailing_solidus = False
    space_before_trailing_solidus = True

    # escaping options
    escape_lt_in_attrs = False
    escape_rcdata = False
    resolve_entities = True

    # miscellaneous options
    alphabetical_attributes = False
    inject_meta_charset = True
    strip_whitespace = False
    sanitize = False

    options = ("quote_attr_values", "quote_char", "use_best_quote_char",
               "omit_optional_tags", "minimize_boolean_attributes",
               "use_trailing_solidus", "space_before_trailing_solidus",
               "escape_lt_in_attrs", "escape_rcdata", "resolve_entities",
               "alphabetical_attributes", "inject_meta_charset",
               "strip_whitespace", "sanitize")

    def __init__(self, **kwargs):
        """Initialize HTMLSerializer

        :arg inject_meta_charset: Whether or not to inject the meta charset.

            Defaults to ``True``.

        :arg quote_attr_values: Whether to quote attribute values that don't
            require quoting per legacy browser behavior (``"legacy"``), when
            required by the standard (``"spec"``), or always (``"always"``).

            Defaults to ``"legacy"``.

        :arg quote_char: Use given quote character for attribute quoting.

            Defaults to ``"`` which will use double quotes unless attribute
            value contains a double quote, in which case single quotes are
            used.

        :arg escape_lt_in_attrs: Whether or not to escape ``<`` in attribute
            values.

            Defaults to ``False``.

        :arg escape_rcdata: Whether to escape characters that need to be
            escaped within normal elements within rcdata elements such as
            style.

            Defaults to ``False``.

        :arg resolve_entities: Whether to resolve named character entities that
            appear in the source tree. The XML predefined entities &lt; &gt;
            &amp; &quot; &apos; are unaffected by this setting.

            Defaults to ``True``.

        :arg strip_whitespace: Whether to remove semantically meaningless
            whitespace. (This compresses all whitespace to a single space
            except within ``pre``.)

            Defaults to ``False``.

        :arg minimize_boolean_attributes: Shortens boolean attributes to give
            just the attribute value, for example::

              <input disabled="disabled">

            becomes::

              <input disabled>

            Defaults to ``True``.

        :arg use_trailing_solidus: Includes a close-tag slash at the end of the
            start tag of void elements (empty elements whose end tag is
            forbidden). E.g. ``<hr/>``.

            Defaults to ``False``.

        :arg space_before_trailing_solidus: Places a space immediately before
            the closing slash in a tag using a trailing solidus. E.g.
            ``<hr />``. Requires ``use_trailing_solidus=True``.

            Defaults to ``True``.

        :arg sanitize: Strip all unsafe or unknown constructs from output.
            See :py:class:`html5lib.filters.sanitizer.Filter`.

            Defaults to ``False``.

        :arg omit_optional_tags: Omit start/end tags that are optional.

            Defaults to ``True``.

        :arg alphabetical_attributes: Reorder attributes to be in alphabetical order.

            Defaults to ``False``.

        """
        unexpected_args = frozenset(kwargs) - frozenset(self.options)
        if len(unexpected_args) > 0:
            raise TypeError("__init__() got an unexpected keyword argument '%s'" % next(iter(unexpected_args)))
        if 'quote_char' in kwargs:
            self.use_best_quote_char = False
        for attr in self.options:
            setattr(self, attr, kwargs.get(attr, getattr(self, attr)))
        self.errors = []
        self.strict = False

    def encode(self, string):
        assert isinstance(string, text_type)
        if self.encoding:
            return string.encode(self.encoding, "htmlentityreplace")
        else:
            return string

    def encodeStrict(self, string):
        assert isinstance(string, text_type)
        if self.encoding:
            return string.encode(self.encoding, "strict")
        else:
            return string

    def _isForeignNamespace(self, namespace):
        return bool(namespace) and namespace != namespaces["html"]

    def _findPrefix(self, namespace):
        """Return an in-scope prefix already bound to namespace, or None."""
        for scope in reversed(self.namespace_scope_stack):
            for prefix, uri in scope["prefixes"].items():
                if uri == namespace:
                    return prefix
        return None

    def _findDefaultNamespace(self):
        """Return the in-scope default namespace URI, or None."""
        for scope in reversed(self.namespace_scope_stack):
            if scope["default"] is not None:
                return scope["default"]
        return None

    def _qualifiedName(self, namespace, name, prefixes=None, default_ns=None):
        """Return the qualified name (e.g. ``xlink:href``) for a token name.

        Namespace declarations (the xmlns namespace) are rendered literally
        rather than looked up, since the token only carries the local name.
        Elements in the in-scope default namespace keep an unprefixed name.

        :arg prefixes: mapping of namespace URI to prefix for the current
            element
        :arg default_ns: the current element's default namespace URI

        """
        if not self._isForeignNamespace(namespace):
            return name
        if namespace == namespaces["xmlns"]:
            return name if name == "xmlns" else "xmlns:" + name
        if namespace == namespaces["xml"]:
            return "xml:" + name
        if namespace == default_ns:
            return name
        if prefixes is None or namespace not in prefixes:
            # No in-scope binding (e.g. an unbalanced EndTag); fall back to
            # the unprefixed local name rather than raising a KeyError.
            return name
        return prefixes[namespace] + ":" + name

    def serialize(self, treewalker, encoding=None):
        # pylint:disable=too-many-nested-blocks
        self.encoding = encoding
        in_cdata = False
        self.errors = []
        # Stack of namespace scopes, one dict per open foreign (non-HTML)
        # element. Each scope has a "prefixes" map (prefix -> namespace URI)
        # and a "default" key holding the default namespace URI (or None).
        # HTML elements don't introduce a scope, preserving the previous
        # serialization behavior for plain HTML trees.
        self.namespace_scope_stack = []

        if encoding and self.inject_meta_charset:
            from .filters.inject_meta_charset import Filter
            treewalker = Filter(treewalker, encoding)
        # Alphabetical attributes is here under the assumption that none of
        # the later filters add or change order of attributes; it needs to be
        # before the sanitizer so escaped elements come out correctly
        if self.alphabetical_attributes:
            from .filters.alphabeticalattributes import Filter
            treewalker = Filter(treewalker)
        # WhitespaceFilter should be used before OptionalTagFilter
        # for maximum efficiently of this latter filter
        if self.strip_whitespace:
            from .filters.whitespace import Filter
            treewalker = Filter(treewalker)
        if self.sanitize:
            from .filters.sanitizer import Filter
            treewalker = Filter(treewalker)
        if self.omit_optional_tags:
            from .filters.optionaltags import Filter
            treewalker = Filter(treewalker)

        for token in treewalker:
            type = token["type"]
            if type == "Doctype":
                doctype = "<!DOCTYPE %s" % token["name"]

                if token["publicId"]:
                    doctype += ' PUBLIC "%s"' % token["publicId"]
                elif token["systemId"]:
                    doctype += " SYSTEM"
                if token["systemId"]:
                    if token["systemId"].find('"') >= 0:
                        if token["systemId"].find("'") >= 0:
                            self.serializeError("System identifier contains both single and double quote characters")
                        quote_char = "'"
                    else:
                        quote_char = '"'
                    doctype += " %s%s%s" % (quote_char, token["systemId"], quote_char)

                doctype += ">"
                yield self.encodeStrict(doctype)

            elif type in ("Characters", "SpaceCharacters"):
                if type == "SpaceCharacters" or in_cdata:
                    if in_cdata and token["data"].find("</") >= 0:
                        self.serializeError("Unexpected </ in CDATA")
                    yield self.encode(token["data"])
                else:
                    yield self.encode(escape(token["data"]))

            elif type in ("StartTag", "EmptyTag"):
                namespace = token.get("namespace")
                name = token["name"]
                foreign = self._isForeignNamespace(namespace)
                if foreign:
                    # Prefixes explicitly declared by xmlns:prefix attributes
                    # on this element: prefix -> namespace URI. They are
                    # serialized verbatim and not re-declared synthetically.
                    explicit_prefixes = {}
                    # Default namespace declared by a bare xmlns attribute,
                    # if any. Elements in this namespace keep an unprefixed
                    # name.
                    explicit_default = None
                    for (attr_ns, attr_name), attr_value in token["data"].items():
                        if attr_ns == namespaces["xmlns"]:
                            if attr_name == "xmlns":
                                explicit_default = attr_value
                            else:
                                explicit_prefixes[attr_name] = attr_value
                        elif attr_ns is None and attr_name == "xmlns":
                            explicit_default = attr_value
                    default_ns = (explicit_default
                                  if explicit_default is not None
                                  else self._findDefaultNamespace())
                    # If the element's namespace is not covered by an explicit
                    # or inherited default namespace, declare it synthetically
                    # so the serialized fragment keeps the element's ns.
                    synthetic_default = None
                    if namespace != default_ns and \
                            self._findPrefix(namespace) is None and \
                            not any(uri == namespace
                                    for uri in explicit_prefixes.values()):
                        synthetic_default = namespace
                        default_ns = namespace
                    # Namespace URIs needing a prefix on this element:
                    # namespaced attributes other than xmlns declarations,
                    # the built-in xml namespace and anything in the default
                    # namespace (whose names stay unprefixed). The element
                    # namespace is added only when it is not the default
                    # namespace.
                    needed = []
                    if namespace != default_ns:
                        needed.append(namespace)
                    for attr_ns, attr_name in token["data"]:
                        if (attr_ns and attr_ns != namespaces["xmlns"] and
                                attr_ns != namespaces["xml"] and
                                attr_ns != default_ns and
                                attr_ns not in needed):
                            needed.append(attr_ns)
                    # Mapping of namespace URI -> prefix for this element,
                    # including bindings inherited from ancestor scopes.
                    element_prefixes = {}
                    synthetic = {}
                    for ns in needed:
                        # Reuse an explicit prefix declaration (xmlns:foo=...)
                        # on this element. Such a declaration shadows any
                        # ancestor binding with the same prefix, so it is the
                        # correct prefix for this namespace here.
                        match = None
                        for prefix, uri in explicit_prefixes.items():
                            if uri == ns:
                                match = prefix
                                break
                        if match is None:
                            # ...otherwise reuse an in-scope ancestor binding
                            # whose prefix isn't redeclared on this element...
                            ancestor_match = self._findPrefix(ns)
                            if ancestor_match is not None and \
                                    ancestor_match not in explicit_prefixes:
                                match = ancestor_match
                        if match is None:
                            # ...otherwise prefer the namespace's well-known
                            # prefix (e.g. xlink) when it is not already taken
                            # on this element, or generate a stable,
                            # non-conflicting prefix and declare it.
                            taken = set()
                            for ancestor in self.namespace_scope_stack:
                                taken.update(ancestor["prefixes"])
                            taken.update(explicit_prefixes)
                            taken.update(synthetic)
                            match = getNamespacePrefixes(
                                ns, dict((p, None) for p in taken))
                            synthetic[match] = ns
                        element_prefixes[ns] = match
                    scope = {"prefixes": dict(explicit_prefixes),
                             "default": default_ns}
                    scope["prefixes"].update(synthetic)
                    self.namespace_scope_stack.append(scope)
                    qname = self._qualifiedName(namespace, name,
                                                element_prefixes, default_ns)
                else:
                    qname = name
                yield self.encodeStrict("<%s" % qname)
                if name in rcdataElements and not self.escape_rcdata:
                    in_cdata = True
                elif in_cdata:
                    self.serializeError("Unexpected child element of a CDATA element")
                attrs = token["data"]
                if foreign and self.alphabetical_attributes:
                    # Sort by the qualified name that will actually be
                    # serialized, rather than by (namespace URI, local name).
                    attrs = sorted(attrs.items(),
                                   key=lambda item: self._qualifiedName(
                                       item[0][0], item[0][1],
                                       element_prefixes, default_ns))
                else:
                    attrs = list(attrs.items())
                for (attr_namespace, attr_name), attr_value in attrs:
                    if foreign:
                        k = self._qualifiedName(attr_namespace, attr_name,
                                                element_prefixes, default_ns)
                    else:
                        k = attr_name
                    v = attr_value
                    yield self.encodeStrict(' ')

                    yield self.encodeStrict(k)
                    if not self.minimize_boolean_attributes or \
                        (k not in booleanAttributes.get(name, tuple()) and
                         k not in booleanAttributes.get("", tuple())):
                        yield self.encodeStrict("=")
                        if self.quote_attr_values == "always" or len(v) == 0:
                            quote_attr = True
                        elif self.quote_attr_values == "spec":
                            quote_attr = _quoteAttributeSpec.search(v) is not None
                        elif self.quote_attr_values == "legacy":
                            quote_attr = _quoteAttributeLegacy.search(v) is not None
                        else:
                            raise ValueError("quote_attr_values must be one of: "
                                             "'always', 'spec', or 'legacy'")
                        v = v.replace("&", "&amp;")
                        if self.escape_lt_in_attrs:
                            v = v.replace("<", "&lt;")
                        if quote_attr:
                            quote_char = self.quote_char
                            if self.use_best_quote_char:
                                if "'" in v and '"' not in v:
                                    quote_char = '"'
                                elif '"' in v and "'" not in v:
                                    quote_char = "'"
                            if quote_char == "'":
                                v = v.replace("'", "&#39;")
                            else:
                                v = v.replace('"', "&quot;")
                            yield self.encodeStrict(quote_char)
                            yield self.encode(v)
                            yield self.encodeStrict(quote_char)
                        else:
                            yield self.encode(v)
                if foreign:
                    # Synthetic xmlns declarations emitted before the tag
                    # closes: the default namespace (when the element's
                    # namespace was not already declared) and any generated
                    # prefixes. Explicit xmlns attributes are emitted with the
                    # regular attributes above.
                    if synthetic_default is not None:
                        yield self.encodeStrict(
                            ' xmlns="%s"' % synthetic_default)
                    for prefix, uri in sorted(synthetic.items()):
                        yield self.encodeStrict(
                            ' xmlns:%s="%s"' % (prefix, uri))
                if name in voidElements and self.use_trailing_solidus:
                    if self.space_before_trailing_solidus:
                        yield self.encodeStrict(" /")
                    else:
                        yield self.encodeStrict("/")
                yield self.encode(">")

            elif type == "EndTag":
                namespace = token.get("namespace")
                name = token["name"]
                if name in rcdataElements:
                    in_cdata = False
                elif in_cdata:
                    self.serializeError("Unexpected child element of a CDATA element")
                if self._isForeignNamespace(namespace):
                    if self.namespace_scope_stack:
                        scope = self.namespace_scope_stack[-1]
                        qname = self._qualifiedName(
                            namespace, name,
                            dict((uri, prefix)
                                 for prefix, uri in scope["prefixes"].items()),
                            scope["default"])
                    else:
                        # Unbalanced EndTag with no matching StartTag.
                        qname = self._qualifiedName(namespace, name, {}, None)
                else:
                    qname = name
                yield self.encodeStrict("</%s>" % qname)
                if self._isForeignNamespace(namespace) and \
                        self.namespace_scope_stack:
                    self.namespace_scope_stack.pop()

            elif type == "Comment":
                data = token["data"]
                if data.find("--") >= 0:
                    self.serializeError("Comment contains --")
                yield self.encodeStrict("<!--%s-->" % token["data"])

            elif type == "Entity":
                name = token["name"]
                key = name + ";"
                if key not in entities:
                    self.serializeError("Entity %s not recognized" % name)
                if self.resolve_entities and key not in xmlEntities:
                    data = entities[key]
                else:
                    data = "&%s;" % name
                yield self.encodeStrict(data)

            else:
                self.serializeError(token["data"])

    def render(self, treewalker, encoding=None):
        """Serializes the stream from the treewalker into a string

        :arg treewalker: the treewalker to serialize

        :arg encoding: the string encoding to use

        :returns: the serialized tree

        Example:

        >>> from html5lib import parse, getTreeWalker
        >>> from html5lib.serializer import HTMLSerializer
        >>> token_stream = parse('<html><body>Hi!</body></html>')
        >>> walker = getTreeWalker('etree')
        >>> serializer = HTMLSerializer(omit_optional_tags=False)
        >>> serializer.render(walker(token_stream))
        '<html><head></head><body>Hi!</body></html>'

        """
        if encoding:
            return b"".join(list(self.serialize(treewalker, encoding)))
        else:
            return "".join(list(self.serialize(treewalker)))

    def serializeError(self, data="XXX ERROR MESSAGE NEEDED"):
        # XXX The idea is to make data mandatory.
        self.errors.append(data)
        if self.strict:
            raise SerializeError


class SerializeError(Exception):
    """Error in serialized tree"""
    pass
