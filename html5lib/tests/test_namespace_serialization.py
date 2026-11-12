"""Acceptance tests for namespace-aware serialization.

Covers:

* SVG/MathML round-trips through the dom, etree and lxml treebuilders,
  including ``xlink:`` and ``xml:`` prefixed attributes and xmlns
  declarations;
* programmatically built ElementTree trees using Clark notation
  (``{namespace}name``) with unknown namespaces;
* prefix conflicts where a well-known prefix is bound to a different URI;
* DOM trees whose elements carry a qualified (``prefix:local``) name;
* alphabetical ordering by qualified name;
* the sanitizer not raising ``KeyError`` on unknown namespaces.

"""
from __future__ import absolute_import, division, unicode_literals

import warnings

import pytest

import html5lib
from html5lib import constants, serialize, treewalkers
from html5lib.serializer import HTMLSerializer

try:
    import lxml.etree
except ImportError:  # pragma: no cover
    lxml = None

try:
    import xml.etree.ElementTree as ElementTree
except ImportError:  # pragma: no cover
    ElementTree = None

TREE_BUILDERS = ["etree", "dom"]
if lxml is not None:
    TREE_BUILDERS.append("lxml")


def render_fragment(markup, tree, **options):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fragment = html5lib.parseFragment(markup, treebuilder=tree)
    options.setdefault("omit_optional_tags", False)
    return serialize(fragment, tree=tree, **options)


@pytest.mark.parametrize("tree", TREE_BUILDERS)
def test_svg_roundtrip_restores_prefixes(tree):
    markup = ('<svg xmlns="http://www.w3.org/2000/svg" '
              'xmlns:xlink="http://www.w3.org/1999/xlink">'
              '<use xlink:href="#a" xml:lang="en"/></svg>')
    output = render_fragment(markup, tree)
    assert output == (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<use xlink:href=#a xml:lang=en></use></svg>')


@pytest.mark.parametrize("tree", TREE_BUILDERS)
def test_mathml_roundtrip_restores_xml_prefix(tree):
    markup = '<math><mi xml:lang="fr">x</mi></math>'
    output = render_fragment(markup, tree)
    assert output == (
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        '<mi xml:lang=fr>x</mi></math>')


@pytest.mark.parametrize("tree", TREE_BUILDERS)
def test_three_treebuilders_agree(tree):
    markup = ('<div><svg xmlns="http://www.w3.org/2000/svg" '
              'xmlns:xlink="http://www.w3.org/1999/xlink">'
              '<use xlink:href="#a" xml:lang="en"/></svg></div>')
    outputs = {name: render_fragment(markup, name)
               for name in TREE_BUILDERS}
    assert len(set(outputs.values())) == 1
    assert outputs[tree].startswith("<div>")


@pytest.mark.parametrize("tree", TREE_BUILDERS)
def test_synthetic_declarations_for_bare_foreign_fragment(tree):
    # No xmlns attributes in the source: the parser still assigns foreign
    # namespaces, so the serializer must add the declarations itself and use
    # the canonical xlink prefix rather than dropping it.
    markup = '<svg><pattern xlink:href="#patt2" id="patt1"></svg>'
    output = render_fragment(markup, tree,
                             alphabetical_attributes=True,
                             quote_attr_values="always")
    assert output == (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<pattern id="patt1" xlink:href="#patt2" '
        'xmlns:xlink="http://www.w3.org/1999/xlink"></pattern></svg>')


def test_programmatic_elementtree_unknown_namespaces():
    # ElementTree stores names as Clark notation {uri}local and does not keep
    # any prefix information; unknown namespaces get stable nsN prefixes with
    # matching xmlns declarations.
    root = ElementTree.Element("{http://example.com/ns1}wrap")
    child = ElementTree.SubElement(root, "{http://example.com/ns2}child")
    child.set("{http://example.com/ns3}attr", "v")
    child.set("{http://example.com/ns1}other", "w")
    output = serialize(root, tree="etree", omit_optional_tags=False)
    assert output == (
        '<wrap xmlns="http://example.com/ns1">'
        '<child ns0:attr=v ns1:other=w '
        'xmlns="http://example.com/ns2" '
        'xmlns:ns0="http://example.com/ns3" '
        'xmlns:ns1="http://example.com/ns1"></child></wrap>')


def test_programmatic_elementtree_wellknown_prefix_preferred():
    # A well-known namespace (xlink) gets its canonical prefix even when the
    # tree was built programmatically without any xmlns declaration.
    root = ElementTree.Element(
        "{%s}use" % constants.namespaces["svg"])
    root.set("{%s}href" % constants.namespaces["xlink"], "#a")
    output = serialize(root, tree="etree", omit_optional_tags=False)
    assert output == (
        '<use xlink:href=#a '
        'xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink"></use>')


def test_generated_prefixes_are_stable_and_non_conflicting():
    # Several distinct attribute namespaces on one element: each gets its own
    # stable nsN prefix, and the numbering is deterministic across runs.
    def build():
        root = ElementTree.Element("{http://example.com/element}wrap")
        for index in range(3):
            root.set("{http://example.com/attr%d}attr%d" % (index, index),
                     str(index))
        return root

    expected = serialize(build(), tree="etree",
                         omit_optional_tags=False)
    assert expected == (
        '<wrap ns0:attr0=0 ns1:attr1=1 ns2:attr2=2 '
        'xmlns="http://example.com/element" '
        'xmlns:ns0="http://example.com/attr0" '
        'xmlns:ns1="http://example.com/attr1" '
        'xmlns:ns2="http://example.com/attr2"></wrap>')
    # Re-serializing an equivalent tree yields the same prefixes.
    assert serialize(build(), tree="etree",
                     omit_optional_tags=False) == expected


def test_generated_prefix_for_attribute_in_different_namespace():
    # Attribute namespaces that differ from the element's default namespace
    # need an explicit prefix and a matching xmlns declaration.
    root = ElementTree.Element("{http://example.com/ns1}wrap")
    child = ElementTree.SubElement(root, "{http://example.com/ns1}child")
    child.set("{http://example.com/ns2}attr", "v")
    output = serialize(child, tree="etree", omit_optional_tags=False)
    assert output == (
        '<child ns0:attr=v xmlns="http://example.com/ns1" '
        'xmlns:ns0="http://example.com/ns2"></child>')


def test_attribute_in_default_namespace_is_unprefixed():
    # An attribute in the same namespace as the element's default namespace
    # stays unprefixed rather than gaining a synthetic "svg:" prefix.
    from html5lib.treewalkers.base import TreeWalker

    class TokenWalker(TreeWalker):
        def __iter__(self):
            for token in self.tree:
                yield token

    svg_ns = constants.namespaces["svg"]
    xmlns_ns = constants.namespaces["xmlns"]
    tokens = [
        {"type": "StartTag", "name": "svg", "namespace": svg_ns,
         "data": {(xmlns_ns, "xmlns"): svg_ns,
                  (svg_ns, "custom"): "v"}},
        {"type": "EndTag", "name": "svg", "namespace": svg_ns},
    ]
    output = HTMLSerializer(omit_optional_tags=False).render(
        TokenWalker(tokens))
    assert output == '<svg xmlns="http://www.w3.org/2000/svg" custom=v></svg>'


def test_prefix_conflict_avoids_taken_wellknown_prefix():
    # Feed tokens directly so the conflicting xmlns:xlink declaration is
    # preserved (programmatic ElementTree trees discard such declarations).
    # The source binds "xlink" to an unrelated URI, so a genuine xlink
    # attribute must get a non-conflicting generated prefix instead.
    from html5lib.treewalkers.base import TreeWalker

    class TokenWalker(TreeWalker):
        def __iter__(self):
            for token in self.tree:
                yield token

    svg_ns = constants.namespaces["svg"]
    xlink_ns = constants.namespaces["xlink"]
    xmlns_ns = constants.namespaces["xmlns"]
    tokens = [
        {"type": "StartTag", "name": "svg", "namespace": svg_ns,
         "data": {(xmlns_ns, "xmlns"): svg_ns,
                  (xmlns_ns, "xlink"): "http://example.com/not-xlink"}},
        {"type": "StartTag", "name": "use", "namespace": svg_ns,
         "data": {(xlink_ns, "href"): "#a"}},
        {"type": "EndTag", "name": "use", "namespace": svg_ns},
        {"type": "EndTag", "name": "svg", "namespace": svg_ns},
    ]
    output = HTMLSerializer(omit_optional_tags=False).render(
        TokenWalker(tokens))
    assert output == (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://example.com/not-xlink">'
        '<use ns0:href=#a '
        'xmlns:ns0="http://www.w3.org/1999/xlink"></use></svg>')


def test_alphabetical_attributes_uses_qualified_names():
    markup = ('<svg xmlns="http://www.w3.org/2000/svg" '
              'xmlns:xlink="http://www.w3.org/1999/xlink">'
              '<pattern xlink:href="#p" id="patt" xml:lang="en"/></svg>')
    output = render_fragment(markup, "etree",
                             alphabetical_attributes=True)
    # id < xlink:href < xml:lang as serialized qualified names.
    assert output.index('id=patt') < output.index('xlink:href') \
        < output.index('xml:lang')


def test_dom_prefixed_element_name_roundtrip():
    from xml.dom import minidom
    dom_impl = minidom.getDOMImplementation()
    doc = dom_impl.createDocument(None, None, None)
    element = doc.createElementNS("http://example.com/foo", "foo:bar")
    attribute = doc.createAttributeNS("http://example.com/foo", "foo:baz")
    attribute.value = "1"
    element.setAttributeNode(attribute)
    fragment = doc.createDocumentFragment()
    fragment.appendChild(element)

    walker = treewalkers.getTreeWalker("dom")(fragment)
    start_token = next(iter(walker))
    # The walker must report the local name, not the DOM's qualified name,
    # so the token shape matches the etree and lxml walkers.
    assert start_token["name"] == "bar"
    assert start_token["namespace"] == "http://example.com/foo"
    assert start_token["data"] == {("http://example.com/foo", "baz"): "1"}


def test_sanitizer_unknown_namespace_does_not_raise():
    root = ElementTree.Element("div")
    element = ElementTree.SubElement(
        root, "{http://example.com/unknown}bar")
    element.set("{http://example.com/unknown}attr", "v")
    element.text = "x"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        output = serialize(root, tree="etree", sanitize=True,
                           omit_optional_tags=False)
    # The disallowed element is escaped; its unknown-namespaced attribute
    # gets a generated prefix instead of triggering a KeyError.
    assert output == '<div>&lt;bar ns0:attr="v"&gt;x&lt;/bar&gt;</div>'


def test_plain_html_output_unchanged():
    markup = '<p class="a" title="b">Hi &amp; bye<br></p>'
    output = render_fragment(markup, "etree", quote_attr_values="always")
    assert output == '<p class="a" title="b">Hi &amp; bye<br></p>'
