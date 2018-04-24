# -*- coding: utf-8 -*-
from __future__ import with_statement

import collections
import contextlib
import glob
import json
import io
import os
import os.path
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest
import warnings

import pytest
from six import StringIO, b, string_types, text_type
from werkzeug.test import Client
from werkzeug.wrappers import Response

import sass
import sassc
from sassutils.builder import Manifest, build_directory
from sassutils.wsgi import SassMiddleware


if os.sep != '/' and os.altsep:  # pragma: no cover (windows)
    def normalize_path(path):
        path = os.path.abspath(os.path.normpath(path))
        return path.replace(os.sep, os.altsep)
else:   # pragma: no cover (non-windows)
    def normalize_path(path):
        return path


A_EXPECTED_CSS = '''\
body {
  background-color: green; }
  body a {
    color: blue; }
'''

A_EXPECTED_CSS_WITH_MAP = '''\
body {
  background-color: green; }
  body a {
    color: blue; }

/*# sourceMappingURL=../a.scss.css.map */'''

A_EXPECTED_MAP = {
    'version': 3,
    'file': 'test/a.css',
    'sources': ['test/a.scss'],
    'names': [],
    'mappings': (
        'AAKA,AAAA,IAAI,CAAC;EAHH,gBAAgB,EAAE,KAAK,GAQxB;EALD,AAEE,IAFE,CAEF,'
        'CAAC,CAAC;IACA,KAAK,EAAE,IAAI,GACZ'
    ),
}

B_EXPECTED_CSS = '''\
b i {
  font-size: 20px; }
'''

B_EXPECTED_CSS_WITH_MAP = '''\
b i {
  font-size: 20px; }

/*# sourceMappingURL=../css/b.scss.css.map */'''

C_EXPECTED_CSS = '''\
body {
  background-color: green; }
  body a {
    color: blue; }

h1 a {
  color: green; }
'''

D_EXPECTED_CSS = u'''\
@charset "UTF-8";
body {
  background-color: green; }
  body a {
    font: '나눔고딕', sans-serif; }
'''

D_EXPECTED_CSS_WITH_MAP = u'''\
@charset "UTF-8";
body {
  background-color: green; }
  body a {
    font: '나눔고딕', sans-serif; }

/*# sourceMappingURL=../css/d.scss.css.map */'''

E_EXPECTED_CSS = '''\
a {
  color: red; }
'''

G_EXPECTED_CSS = '''\
body {
  font: 100% Helvetica, sans-serif;
  color: #333;
  height: 1.42857; }
'''

G_EXPECTED_CSS_WITH_PRECISION_8 = '''\
body {
  font: 100% Helvetica, sans-serif;
  color: #333;
  height: 1.42857143; }
'''

SUBDIR_RECUR_EXPECTED_CSS = '''\
body p {
  color: blue; }
'''


class BaseTestCase(unittest.TestCase):

    def assert_source_map_equal(self, expected, actual):
        if isinstance(expected, string_types):
            expected = json.loads(expected)
        if isinstance(actual, string_types):
            actual = json.loads(actual)
        assert expected == actual

    def assert_source_map_file(self, expected, filename):
        with open(filename) as f:
            try:
                tree = json.load(f)
            except ValueError as e:  # pragma: no cover
                f.seek(0)
                msg = '{0!s}\n\n{1}:\n\n{2}'.format(e, filename, f.read())
                raise ValueError(msg)
        self.assert_source_map_equal(expected, tree)


class SassTestCase(BaseTestCase):

    def test_version(self):
        assert re.match(r'^\d+\.\d+\.\d+$', sass.__version__)

    def test_output_styles(self):
        assert isinstance(sass.OUTPUT_STYLES, collections.Mapping)
        assert 'nested' in sass.OUTPUT_STYLES

    def test_and_join(self):
        self.assertEqual(
            'Korea, Japan, China, and Taiwan',
            sass.and_join(['Korea', 'Japan', 'China', 'Taiwan'])
        )
        self.assertEqual(
            'Korea, and Japan',
            sass.and_join(['Korea', 'Japan'])
        )
        assert 'Korea' == sass.and_join(['Korea'])
        assert '' == sass.and_join([])


class CompileTestCase(BaseTestCase):

    def test_compile_required_arguments(self):
        self.assertRaises(TypeError, sass.compile)

    def test_compile_takes_only_keywords(self):
        self.assertRaises(TypeError, sass.compile, 'a { color: blue; }')

    def test_compile_exclusive_arguments(self):
        self.assertRaises(TypeError, sass.compile,
                          string='a { color: blue; }', filename='test/a.scss')
        self.assertRaises(TypeError, sass.compile,
                          string='a { color: blue; }', dirname='test/')
        self.assertRaises(TypeError,  sass.compile,
                          filename='test/a.scss', dirname='test/')

    def test_compile_invalid_output_style(self):
        self.assertRaises(TypeError, sass.compile,
                          string='a { color: blue; }',
                          output_style=['compact'])
        self.assertRaises(TypeError,  sass.compile,
                          string='a { color: blue; }', output_style=123j)
        self.assertRaises(ValueError,  sass.compile,
                          string='a { color: blue; }', output_style='invalid')

    def test_compile_invalid_source_comments(self):
        self.assertRaises(TypeError, sass.compile,
                          string='a { color: blue; }',
                          source_comments=['line_numbers'])
        self.assertRaises(TypeError,  sass.compile,
                          string='a { color: blue; }', source_comments=123j)
        self.assertRaises(TypeError,  sass.compile,
                          string='a { color: blue; }',
                          source_comments='invalid')

    def test_compile_disallows_arbitrary_arguments(self):
        for args in (
                {'string': 'a{b:c}'},
                {'filename': 'test/a.scss'},
                {'dirname': ('test', '/dev/null')},
        ):
            with pytest.raises(TypeError) as excinfo:
                sass.compile(herp='derp', harp='darp', **args)
            msg, = excinfo.value.args
            assert msg == (
                "compile() got unexpected keyword argument(s) 'harp', 'herp'"
            )

    def test_compile_string(self):
        actual = sass.compile(string='a { b { color: blue; } }')
        assert actual == 'a b {\n  color: blue; }\n'
        commented = sass.compile(string='''a {
            b { color: blue; }
            color: red;
        }''', source_comments=True)
        assert commented == '''/* line 1, stdin */
a {
  color: red; }
  /* line 2, stdin */
  a b {
    color: blue; }
'''
        actual = sass.compile(string=u'a { color: blue; } /* 유니코드 */')
        self.assertEqual(
            u'''@charset "UTF-8";
a {
  color: blue; }

/* 유니코드 */
''',
            actual
        )
        self.assertRaises(sass.CompileError, sass.compile,
                          string='a { b { color: blue; }')
        # sass.CompileError should be a subtype of ValueError
        self.assertRaises(ValueError, sass.compile,
                          string='a { b { color: blue; }')
        self.assertRaises(TypeError, sass.compile, string=1234)
        self.assertRaises(TypeError, sass.compile, string=[])

    def test_compile_string_sass_style(self):
        actual = sass.compile(string='a\n\tb\n\t\tcolor: blue;',
                              indented=True)
        assert actual == 'a b {\n  color: blue; }\n'

    def test_importer_one_arg(self):
        """Demonstrates one-arg importers + chaining."""
        def importer_returning_one_argument(path):
            assert type(path) is text_type
            return (
                # Trigger the import of an actual file
                ('test/b.scss',),
                (path, '.{0}-one-arg {{ color: blue; }}'.format(path)),
            )

        ret = sass.compile(
            string="@import 'foo';",
            importers=((0, importer_returning_one_argument),),
            output_style='compressed',
        )
        assert ret == 'b i{font-size:20px}.foo-one-arg{color:blue}\n'

    def test_importer_does_not_handle_returns_None(self):
        def importer_one(path):
            if path == 'one':
                return ((path, 'a { color: red; }'),)

        def importer_two(path):
            assert path == 'two'
            return ((path, 'b { color: blue; }'),)

        ret = sass.compile(
            string='@import "one"; @import "two";',
            importers=((0, importer_one), (0, importer_two)),
            output_style='compressed',
        )
        assert ret == 'a{color:red}b{color:blue}\n'

    def test_importers_other_iterables(self):
        def importer_one(path):
            if path == 'one':
                # Need to do this to avoid returning empty generator
                def gen():
                    yield (path, 'a { color: red; }')
                    yield (path + 'other', 'b { color: orange; }')
                return gen()

        def importer_two(path):
            assert path == 'two'
            # List of lists
            return [
                [path, 'c { color: yellow; }'],
                [path + 'other', 'd { color: green; }'],
            ]

        ret = sass.compile(
            string='@import "one"; @import "two";',
            # Importers can also be lists
            importers=[[0, importer_one], [0, importer_two]],
            output_style='compressed',
        )
        assert ret == (
            'a{color:red}b{color:orange}c{color:yellow}d{color:green}\n'
        )

    def test_importers_srcmap(self):
        def importer_with_srcmap(path):
            return (
                (
                    path,
                    'a { color: red; }',
                    json.dumps({
                        "version": 3,
                        "sources": [
                            path + ".db"
                        ],
                        "mappings": ";AAAA,CAAC,CAAC;EAAE,KAAK,EAAE,GAAI,GAAI",
                    }),
                ),
            )

        # This exercises the code, but I don't know what the outcome is
        # supposed to be.
        ret = sass.compile(
            string='@import "test";',
            importers=((0, importer_with_srcmap),),
            output_style='compressed',
        )
        assert ret == 'a{color:red}\n'

    def test_importers_raises_exception(self):
        def importer(path):
            raise ValueError('Bad path: {0}'.format(path))

        with assert_raises_compile_error(RegexMatcher(
                r'^Error: \n'
                r'       Traceback \(most recent call last\):\n'
                r'.+'
                r'ValueError: Bad path: hi\n'
                r'        on line 1 of stdin\n'
                r'>> @import "hi";\n'
                r'   --------\^\n'
        )):
            sass.compile(string='@import "hi";', importers=((0, importer),))

    def test_importer_returns_wrong_tuple_size_zero(self):
        def importer(path):
            return ((),)

        with assert_raises_compile_error(RegexMatcher(
                r'^Error: \n'
                r'       Traceback \(most recent call last\):\n'
                r'.+'
                r'ValueError: Expected importer result to be a tuple of '
                r'length \(1, 2, 3\) but got 0: \(\)\n'
                r'        on line 1 of stdin\n'
                r'>> @import "hi";\n'
                r'   --------\^\n'
        )):
            sass.compile(string='@import "hi";', importers=((0, importer),))

    def test_importer_returns_wrong_tuple_size_too_big(self):
        def importer(path):
            return (('a', 'b', 'c', 'd'),)

        with assert_raises_compile_error(RegexMatcher(
                r'^Error: \n'
                r'       Traceback \(most recent call last\):\n'
                r'.+'
                r'ValueError: Expected importer result to be a tuple of '
                r"length \(1, 2, 3\) but got 4: \('a', 'b', 'c', 'd'\)\n"
                r'        on line 1 of stdin\n'
                r'>> @import "hi";\n'
                r'   --------\^\n'
        )):
            sass.compile(string='@import "hi";', importers=((0, importer),))

    def test_compile_string_deprecated_source_comments_line_numbers(self):
        source = '''a {
            b { color: blue; }
            color: red;
        }'''
        expected = sass.compile(string=source, source_comments=True)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            actual = sass.compile(string=source,
                                  source_comments='line_numbers')
            assert len(w) == 1
            assert issubclass(w[-1].category, DeprecationWarning)
        assert expected == actual

    def test_compile_filename(self):
        actual = sass.compile(filename='test/a.scss')
        assert actual == A_EXPECTED_CSS
        actual = sass.compile(filename='test/c.scss')
        assert actual == C_EXPECTED_CSS
        actual = sass.compile(filename='test/d.scss')
        assert D_EXPECTED_CSS == actual
        actual = sass.compile(filename='test/e.scss')
        assert actual == E_EXPECTED_CSS
        self.assertRaises(IOError, sass.compile,
                          filename='test/not-exist.sass')
        self.assertRaises(TypeError, sass.compile, filename=1234)
        self.assertRaises(TypeError, sass.compile, filename=[])

    def test_compile_source_map(self):
        filename = 'test/a.scss'
        actual, source_map = sass.compile(
            filename=filename,
            source_map_filename='a.scss.css.map'
        )
        assert A_EXPECTED_CSS_WITH_MAP == actual
        self.assert_source_map_equal(A_EXPECTED_MAP, source_map)

    def test_compile_source_map_deprecated_source_comments_map(self):
        filename = 'test/a.scss'
        expected, expected_map = sass.compile(
            filename=filename,
            source_map_filename='a.scss.css.map'
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            actual, actual_map = sass.compile(
                filename=filename,
                source_comments='map',
                source_map_filename='a.scss.css.map'
            )
            assert len(w) == 1
            assert issubclass(w[-1].category, DeprecationWarning)
        assert expected == actual
        self.assert_source_map_equal(expected_map, actual_map)

    def test_compile_with_precision(self):
        actual = sass.compile(filename='test/g.scss')
        assert actual == G_EXPECTED_CSS
        actual = sass.compile(filename='test/g.scss', precision=8)
        assert actual == G_EXPECTED_CSS_WITH_PRECISION_8

    def test_regression_issue_2(self):
        actual = sass.compile(string='''
            @media (min-width: 980px) {
                a {
                    color: red;
                }
            }
        ''')
        normalized = re.sub(r'\s+', '', actual)
        assert normalized == '@media(min-width:980px){a{color:red;}}'

    def test_regression_issue_11(self):
        actual = sass.compile(string='''
            $foo: 3;
            @media (max-width: $foo) {
                body { color: black; }
            }
        ''')
        normalized = re.sub(r'\s+', '', actual)
        assert normalized == '@media(max-width:3){body{color:black;}}'


class BuilderTestCase(BaseTestCase):

    def setUp(self):
        self.temp_path = tempfile.mkdtemp()
        self.sass_path = os.path.join(self.temp_path, 'sass')
        self.css_path = os.path.join(self.temp_path, 'css')
        shutil.copytree('test', self.sass_path)

    def tearDown(self):
        shutil.rmtree(self.temp_path)

    def test_builder_build_directory(self):
        css_path = self.css_path
        result_files = build_directory(self.sass_path, css_path)
        assert len(result_files) == 7
        assert 'a.scss.css' == result_files['a.scss']
        with io.open(
            os.path.join(css_path, 'a.scss.css'), encoding='UTF-8',
        ) as f:
            css = f.read()
        assert A_EXPECTED_CSS == css
        assert 'b.scss.css' == result_files['b.scss']
        with io.open(
            os.path.join(css_path, 'b.scss.css'), encoding='UTF-8',
        ) as f:
            css = f.read()
        assert B_EXPECTED_CSS == css
        assert 'c.scss.css' == result_files['c.scss']
        with io.open(
            os.path.join(css_path, 'c.scss.css'), encoding='UTF-8',
        ) as f:
            css = f.read()
        assert C_EXPECTED_CSS == css
        assert 'd.scss.css' == result_files['d.scss']
        with io.open(
            os.path.join(css_path, 'd.scss.css'), encoding='UTF-8',
        ) as f:
            css = f.read()
        assert D_EXPECTED_CSS == css
        assert 'e.scss.css' == result_files['e.scss']
        with io.open(
            os.path.join(css_path, 'e.scss.css'), encoding='UTF-8',
        ) as f:
            css = f.read()
        assert E_EXPECTED_CSS == css
        self.assertEqual(
            os.path.join('subdir', 'recur.scss.css'),
            result_files[os.path.join('subdir', 'recur.scss')]
        )
        with io.open(
            os.path.join(css_path, 'g.scss.css'), encoding='UTF-8',
        ) as f:
            css = f.read()
        assert G_EXPECTED_CSS == css
        self.assertEqual(
            os.path.join('subdir', 'recur.scss.css'),
            result_files[os.path.join('subdir', 'recur.scss')]
        )
        with io.open(
            os.path.join(css_path, 'subdir', 'recur.scss.css'),
            encoding='UTF-8',
        ) as f:
            css = f.read()
        assert SUBDIR_RECUR_EXPECTED_CSS == css

    def test_output_style(self):
        css_path = self.css_path
        result_files = build_directory(self.sass_path, css_path,
                                       output_style='compressed')
        assert len(result_files) == 7
        assert 'a.scss.css' == result_files['a.scss']
        with io.open(
            os.path.join(css_path, 'a.scss.css'), encoding='UTF-8',
        ) as f:
            css = f.read()
        self.assertEqual('body{background-color:green}body a{color:blue}\n',
                         css)


class ManifestTestCase(BaseTestCase):

    def test_normalize_manifests(self):
        manifests = Manifest.normalize_manifests({
            'package': 'sass/path',
            'package.name': ('sass/path', 'css/path'),
            'package.name2': Manifest('sass/path', 'css/path')
        })
        assert len(manifests) == 3
        assert isinstance(manifests['package'], Manifest)
        assert manifests['package'].sass_path == 'sass/path'
        assert manifests['package'].css_path == 'sass/path'
        assert isinstance(manifests['package.name'], Manifest)
        assert manifests['package.name'].sass_path == 'sass/path'
        assert manifests['package.name'].css_path == 'css/path'
        assert isinstance(manifests['package.name2'], Manifest)
        assert manifests['package.name2'].sass_path == 'sass/path'
        assert manifests['package.name2'].css_path == 'css/path'

    def test_build_one(self):
        with tempdir() as d:
            src_path = os.path.join(d, 'test')

            def test_source_path(*path):
                return normalize_path(os.path.join(d, 'test', *path))

            def replace_source_path(s, name):
                return s.replace('SOURCE', test_source_path(name))

            shutil.copytree('test', src_path)
            m = Manifest(sass_path='test', css_path='css')
            m.build_one(d, 'a.scss')
            with open(os.path.join(d, 'css', 'a.scss.css')) as f:
                assert A_EXPECTED_CSS == f.read()
            m.build_one(d, 'b.scss', source_map=True)
            with io.open(
                os.path.join(d, 'css', 'b.scss.css'), encoding='UTF-8',
            ) as f:
                self.assertEqual(
                    replace_source_path(B_EXPECTED_CSS_WITH_MAP, 'b.scss'),
                    f.read(),
                )
            self.assert_source_map_file(
                {
                    'version': 3,
                    'file': '../test/b.css',
                    'sources': ['../test/b.scss'],
                    'names': [],
                    'mappings': (
                        'AAAA,AACE,CADD,CACC,CAAC,CAAC;EACA,SAAS,EAAE,IAAI,'
                        'GAChB'
                    ),
                },
                os.path.join(d, 'css', 'b.scss.css.map')
            )
            m.build_one(d, 'd.scss', source_map=True)
            with io.open(
                os.path.join(d, 'css', 'd.scss.css'), encoding='UTF-8',
            ) as f:
                assert (
                    replace_source_path(D_EXPECTED_CSS_WITH_MAP, 'd.scss') ==
                    f.read()
                )
            self.assert_source_map_file(
                {
                    'version': 3,
                    'file': '../test/d.css',
                    'sources': ['../test/d.scss'],
                    'names': [],
                    'mappings': (
                        ';AAKA,AAAA,IAAI,CAAC;EAHH,gBAAgB,EAAE,KAAK,GAQxB;'
                        'EALD,AAEE,IAFE,CAEF,CAAC,CAAC;IACA,IAAI,EAAE,sBAAsB,'
                        'GAC7B'
                    ),
                },
                os.path.join(d, 'css', 'd.scss.css.map')
            )


class WsgiTestCase(BaseTestCase):

    @staticmethod
    def sample_wsgi_app(environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return environ['PATH_INFO'],

    def test_wsgi_sass_middleware(self):
        with tempdir() as css_dir:
            src_dir = os.path.join(css_dir, 'src')
            shutil.copytree('test', src_dir)
            app = SassMiddleware(self.sample_wsgi_app, {
                __name__: (src_dir, css_dir, '/static')
            })
            client = Client(app, Response)
            r = client.get('/asdf')
            assert r.status_code == 200
            self.assertEqual(b'/asdf', r.data)
            assert r.mimetype == 'text/plain'
            r = client.get('/static/a.scss.css')
            assert r.status_code == 200
            self.assertEqual(
                b(A_EXPECTED_CSS_WITH_MAP),
                r.data,
            )
            assert r.mimetype == 'text/css'
            r = client.get('/static/not-exists.sass.css')
            assert r.status_code == 200
            self.assertEqual(b'/static/not-exists.sass.css', r.data)
            assert r.mimetype == 'text/plain'


class DistutilsTestCase(BaseTestCase):

    def tearDown(self):
        for filename in self.list_built_css():
            os.remove(filename)

    def css_path(self, *args):
        return os.path.join(
            os.path.dirname(__file__),
            'testpkg', 'testpkg', 'static', 'css',
            *args
        )

    def list_built_css(self):
        return glob.glob(self.css_path('*.scss.css'))

    def build_sass(self, *args):
        testpkg_path = os.path.join(os.path.dirname(__file__), 'testpkg')
        return subprocess.call(
            [sys.executable, 'setup.py', 'build_sass'] + list(args),
            cwd=os.path.abspath(testpkg_path)
        )

    def test_build_sass(self):
        rv = self.build_sass()
        assert rv == 0
        self.assertEqual(
            ['a.scss.css'],
            list(map(os.path.basename, self.list_built_css()))
        )
        with open(self.css_path('a.scss.css')) as f:
            self.assertEqual(
                'p a {\n  color: red; }\n\np b {\n  color: blue; }\n',
                f.read()
            )

    def test_output_style(self):
        rv = self.build_sass('--output-style', 'compressed')
        assert rv == 0
        with open(self.css_path('a.scss.css')) as f:
            self.assertEqual(
                'p a{color:red}p b{color:blue}\n',
                f.read()
            )


class SasscTestCase(BaseTestCase):

    def setUp(self):
        self.out = StringIO()
        self.err = StringIO()

    def test_no_args(self):
        exit_code = sassc.main(['sassc'], self.out, self.err)
        assert exit_code == 2
        err = self.err.getvalue()
        assert err.strip().endswith('error: too few arguments'), \
            'actual error message is: ' + repr(err)
        assert '' == self.out.getvalue()

    def test_three_args(self):
        exit_code = sassc.main(
            ['sassc', 'a.scss', 'b.scss', 'c.scss'],
            self.out, self.err
        )
        assert exit_code == 2
        err = self.err.getvalue()
        assert err.strip().endswith('error: too many arguments'), \
            'actual error message is: ' + repr(err)
        assert self.out.getvalue() == ''

    def test_sassc_stdout(self):
        exit_code = sassc.main(['sassc', 'test/a.scss'], self.out, self.err)
        assert exit_code == 0
        assert self.err.getvalue() == ''
        assert A_EXPECTED_CSS.strip() == self.out.getvalue().strip()

    def test_sassc_output(self):
        fd, tmp = tempfile.mkstemp('.css')
        try:
            os.close(fd)
            exit_code = sassc.main(['sassc', 'test/a.scss', tmp],
                                   self.out, self.err)
            assert exit_code == 0
            assert self.err.getvalue() == ''
            assert self.out.getvalue() == ''
            with io.open(tmp, encoding='UTF-8', newline='') as f:
                assert A_EXPECTED_CSS.strip() == f.read().strip()
        finally:
            os.remove(tmp)

    def test_sassc_output_unicode(self):
        fd, tmp = tempfile.mkstemp('.css')
        try:
            os.close(fd)
            exit_code = sassc.main(['sassc', 'test/d.scss', tmp],
                                   self.out, self.err)
            assert exit_code == 0
            assert self.err.getvalue() == ''
            assert self.out.getvalue() == ''
            with io.open(tmp, encoding='UTF-8') as f:
                assert D_EXPECTED_CSS.strip() == f.read().strip()
        finally:
            os.remove(tmp)

    def test_sassc_source_map_without_css_filename(self):
        exit_code = sassc.main(['sassc', '-m', 'a.scss'], self.out, self.err)
        assert exit_code == 2
        err = self.err.getvalue()
        assert err.strip().endswith('error: -m/-g/--sourcemap requires '
                                    'the second argument, the output css '
                                    'filename.'), \
            'actual error message is: ' + repr(err)
        assert self.out.getvalue() == ''


@contextlib.contextmanager
def tempdir():
    tmpdir = tempfile.mkdtemp()
    try:
        yield tmpdir
    finally:
        shutil.rmtree(tmpdir)


def write_file(filename, contents):
    with open(filename, 'w') as f:
        f.write(contents)


class CompileDirectoriesTest(unittest.TestCase):

    def test_directory_does_not_exist(self):
        with pytest.raises(OSError):
            sass.compile(dirname=('i_dont_exist_lol', 'out'))

    def test_successful(self):
        with tempdir() as tmpdir:
            input_dir = os.path.join(tmpdir, 'input')
            output_dir = os.path.join(tmpdir, 'output')
            os.makedirs(os.path.join(input_dir, 'foo'))
            write_file(os.path.join(input_dir, 'f1.scss'),
                       'a { b { width: 100%; } }')
            write_file(os.path.join(input_dir, 'foo/f2.scss'),
                       'foo { width: 100%; }')
            # Make sure we don't compile non-scss files
            write_file(os.path.join(input_dir, 'baz.txt'), 'Hello der')

            sass.compile(dirname=(input_dir, output_dir))
            assert os.path.exists(output_dir)
            assert os.path.exists(os.path.join(output_dir, 'foo'))
            assert os.path.exists(os.path.join(output_dir, 'f1.css'))
            assert os.path.exists(os.path.join(output_dir, 'foo/f2.css'))
            assert not os.path.exists(os.path.join(output_dir, 'baz.txt'))

            contentsf1 = open(os.path.join(output_dir, 'f1.css')).read()
            contentsf2 = open(os.path.join(output_dir, 'foo/f2.css')).read()
            assert contentsf1 == 'a b {\n  width: 100%; }\n'
            assert contentsf2 == 'foo {\n  width: 100%; }\n'

    def test_compile_directories_unicode(self):
        with tempdir() as tmpdir:
            input_dir = os.path.join(tmpdir, 'input')
            output_dir = os.path.join(tmpdir, 'output')
            os.makedirs(input_dir)
            with io.open(
                os.path.join(input_dir, 'test.scss'), 'w', encoding='UTF-8',
            ) as f:
                f.write(u'a { content: "☃"; }')
            # Raised a UnicodeEncodeError in py2 before #82 (issue #72)
            # Also raised a UnicodeEncodeError in py3 if the default encoding
            # couldn't represent it (such as cp1252 on windows)
            sass.compile(dirname=(input_dir, output_dir))
            assert os.path.exists(os.path.join(output_dir, 'test.css'))

    def test_ignores_underscored_files(self):
        with tempdir() as tmpdir:
            input_dir = os.path.join(tmpdir, 'input')
            output_dir = os.path.join(tmpdir, 'output')
            os.mkdir(input_dir)
            write_file(os.path.join(input_dir, 'f1.scss'), '@import "f2";')
            write_file(os.path.join(input_dir, '_f2.scss'), 'a{color:red}')

            sass.compile(dirname=(input_dir, output_dir))
            assert not os.path.exists(os.path.join(output_dir, '_f2.css'))

    def test_error(self):
        with tempdir() as tmpdir:
            input_dir = os.path.join(tmpdir, 'input')
            os.makedirs(input_dir)
            write_file(os.path.join(input_dir, 'bad.scss'), 'a {')

            with pytest.raises(sass.CompileError) as excinfo:
                sass.compile(
                    dirname=(input_dir, os.path.join(tmpdir, 'output'))
                )
            msg, = excinfo.value.args
            assert msg.startswith('Error: Invalid CSS after ')


class SassFunctionTest(unittest.TestCase):

    def test_from_lambda(self):
        # Hack for https://gitlab.com/pycqa/flake8/issues/117
        def noop(x):
            return x
        lambda_ = noop(lambda abc, d: None)  # pragma: no branch (lambda)
        sf = sass.SassFunction.from_lambda('func_name', lambda_)
        assert 'func_name' == sf.name
        assert ('$abc', '$d') == sf.arguments
        assert sf.callable_ is lambda_

    def test_from_named_function(self):
        sf = sass.SassFunction.from_named_function(identity)
        assert 'identity' == sf.name
        assert ('$x',) == sf.arguments
        assert sf.callable_ is identity

    def test_sigature(self):
        sf = sass.SassFunction(  # pragma: no branch (doesn't run lambda)
            'func-name',
            ('$a', '$bc', '$d'),
            lambda a, bc, d: None
        )
        assert 'func-name($a, $bc, $d)' == sf.signature
        assert sf.signature == str(sf)


@pytest.mark.parametrize(  # pragma: no branch (never runs lambdas)
    'func',
    (lambda bar='womp': None, lambda *args: None, lambda **kwargs: None),
)
def test_sass_func_type_errors(func):
    with pytest.raises(TypeError):
        sass.SassFunction.from_lambda('funcname', func)


class SassTypesTest(unittest.TestCase):
    def test_number_no_conversion(self):
        num = sass.SassNumber(123., u'px')
        assert type(num.value) is float, type(num.value)
        assert type(num.unit) is text_type, type(num.unit)

    def test_number_conversion(self):
        num = sass.SassNumber(123, b'px')
        assert type(num.value) is float, type(num.value)
        assert type(num.unit) is text_type, type(num.unit)

    def test_color_no_conversion(self):
        color = sass.SassColor(1., 2., 3., .5)
        assert type(color.r) is float, type(color.r)
        assert type(color.g) is float, type(color.g)
        assert type(color.b) is float, type(color.b)
        assert type(color.a) is float, type(color.a)

    def test_color_conversion(self):
        color = sass.SassColor(1, 2, 3, 1)
        assert type(color.r) is float, type(color.r)
        assert type(color.g) is float, type(color.g)
        assert type(color.b) is float, type(color.b)
        assert type(color.a) is float, type(color.a)

    def test_sass_list_no_conversion(self):
        lst = sass.SassList(('foo', 'bar'), sass.SASS_SEPARATOR_COMMA)
        assert type(lst.items) is tuple, type(lst.items)
        assert lst.separator is sass.SASS_SEPARATOR_COMMA, lst.separator

    def test_sass_list_conversion(self):
        lst = sass.SassList(['foo', 'bar'], sass.SASS_SEPARATOR_SPACE)
        assert type(lst.items) is tuple, type(lst.items)
        assert lst.separator is sass.SASS_SEPARATOR_SPACE, lst.separator

    def test_sass_warning_no_conversion(self):
        warn = sass.SassWarning(u'error msg')
        assert type(warn.msg) is text_type, type(warn.msg)

    def test_sass_warning_no_conversion_bytes_message(self):
        warn = sass.SassWarning(b'error msg')
        assert type(warn.msg) is text_type, type(warn.msg)

    def test_sass_error_no_conversion(self):
        err = sass.SassError(u'error msg')
        assert type(err.msg) is text_type, type(err.msg)

    def test_sass_error_conversion(self):
        err = sass.SassError(b'error msg')
        assert type(err.msg) is text_type, type(err.msg)


def raises():
    raise AssertionError('foo')


def returns_warning():
    return sass.SassWarning('This is a warning')


def returns_error():
    return sass.SassError('This is an error')


def returns_unknown():
    """Tuples are a not-supported type."""
    return 1, 2, 3


def returns_true():
    return True


def returns_false():
    return False


def returns_none():
    return None


def returns_unicode():
    return u'☃'


def returns_bytes():
    return u'☃'.encode('UTF-8')


def returns_number():
    return sass.SassNumber(5, 'px')


def returns_color():
    return sass.SassColor(1, 2, 3, .5)


def returns_comma_list():
    return sass.SassList(('Arial', 'sans-serif'), sass.SASS_SEPARATOR_COMMA)


def returns_space_list():
    return sass.SassList(('medium', 'none'), sass.SASS_SEPARATOR_SPACE)


def returns_bracketed_list():
    return sass.SassList(
        ('hello', 'ohai'), sass.SASS_SEPARATOR_SPACE, bracketed=True,
    )


def returns_py_dict():
    return {'foo': 'bar'}


def returns_map():
    return sass.SassMap([('foo', 'bar')])


def identity(x):
    """This has the side-effect of bubbling any exceptions we failed to process
    in C land

    """
    import sys  # noqa
    return x


custom_functions = frozenset([
    sass.SassFunction('raises', (), raises),
    sass.SassFunction('returns_warning', (), returns_warning),
    sass.SassFunction('returns_error', (), returns_error),
    sass.SassFunction('returns_unknown', (), returns_unknown),
    sass.SassFunction('returns_true', (), returns_true),
    sass.SassFunction('returns_false', (), returns_false),
    sass.SassFunction('returns_none', (), returns_none),
    sass.SassFunction('returns_unicode', (), returns_unicode),
    sass.SassFunction('returns_bytes', (), returns_bytes),
    sass.SassFunction('returns_number', (), returns_number),
    sass.SassFunction('returns_color', (), returns_color),
    sass.SassFunction('returns_comma_list', (), returns_comma_list),
    sass.SassFunction('returns_space_list', (), returns_space_list),
    sass.SassFunction('returns_bracketed_list', (), returns_bracketed_list),
    sass.SassFunction('returns_py_dict', (), returns_py_dict),
    sass.SassFunction('returns_map', (), returns_map),
    sass.SassFunction('identity', ('$x',), identity),
])

custom_function_map = {
    'raises': raises,
    'returns_warning': returns_warning,
    'returns_error': returns_error,
    'returns_unknown': returns_unknown,
    'returns_true': returns_true,
    'returns_false': returns_false,
    'returns_none': returns_none,
    'returns_unicode': returns_unicode,
    'returns_bytes': returns_bytes,
    'returns_number': returns_number,
    'returns_color': returns_color,
    'returns_comma_list': returns_comma_list,
    'returns_space_list': returns_space_list,
    'returns_bracketed_list': returns_bracketed_list,
    'returns_py_dict': returns_py_dict,
    'returns_map': returns_map,
    'identity': identity,
}

custom_function_set = frozenset([
    raises,
    returns_warning,
    returns_error,
    returns_unknown,
    returns_true,
    returns_false,
    returns_none,
    returns_unicode,
    returns_bytes,
    returns_number,
    returns_color,
    returns_comma_list,
    returns_space_list,
    returns_bracketed_list,
    returns_py_dict,
    returns_map,
    identity,
])


def compile_with_func(s):
    result = sass.compile(
        string=s,
        custom_functions=custom_functions,
        output_style='compressed',
    )
    map_result = sass.compile(
        string=s,
        custom_functions=custom_function_map,
        output_style='compressed',
    )
    assert result == map_result
    set_result = sass.compile(
        string=s,
        custom_functions=custom_function_set,
        output_style='compressed',
    )
    assert map_result == set_result
    return result


@contextlib.contextmanager
def assert_raises_compile_error(expected):
    with pytest.raises(sass.CompileError) as excinfo:
        yield
    msg, = excinfo.value.args
    assert msg == expected, (msg, expected)


class RegexMatcher(object):
    def __init__(self, reg, flags=None):
        self.reg = re.compile(reg, re.MULTILINE | re.DOTALL)

    def __eq__(self, other):
        return bool(self.reg.match(other))


class CustomFunctionsTest(unittest.TestCase):

    def test_raises(self):
        with assert_raises_compile_error(RegexMatcher(
                r'^Error: error in C function raises: \n'
                r'       Traceback \(most recent call last\):\n'
                r'.+'
                r'AssertionError: foo\n'
                r'        on line 1 of stdin, in function `raises`\n'
                r'        from line 1 of stdin\n'
                r'>> a { content: raises\(\); }\n'
                r'   -------------\^\n$'
        )):
            compile_with_func('a { content: raises(); }')

    def test_warning(self):
        with assert_raises_compile_error(
                'Error: warning in C function returns_warning: '
                'This is a warning\n'
                '        on line 1 of stdin, in function `returns_warning`\n'
                '        from line 1 of stdin\n'
                '>> a { content: returns_warning(); }\n'
                '   -------------^\n'
        ):
            compile_with_func('a { content: returns_warning(); }')

    def test_error(self):
        with assert_raises_compile_error(
                'Error: error in C function returns_error: '
                'This is an error\n'
                '        on line 1 of stdin, in function `returns_error`\n'
                '        from line 1 of stdin\n'
                '>> a { content: returns_error(); }\n'
                '   -------------^\n'
        ):
            compile_with_func('a { content: returns_error(); }')

    def test_returns_unknown_object(self):
        with assert_raises_compile_error(
                'Error: error in C function returns_unknown: '
                'Unexpected type: `tuple`.\n'
                '       Expected one of:\n'
                '       - None\n'
                '       - bool\n'
                '       - str\n'
                '       - SassNumber\n'
                '       - SassColor\n'
                '       - SassList\n'
                '       - dict\n'
                '       - SassMap\n'
                '       - SassWarning\n'
                '       - SassError\n'
                '        on line 1 of stdin, in function `returns_unknown`\n'
                '        from line 1 of stdin\n'
                '>> a { content: returns_unknown(); }\n'
                '   -------------^\n'
        ):
            compile_with_func('a { content: returns_unknown(); }')

    def test_none(self):
        self.assertEqual(
            compile_with_func('a {color: #fff; content: returns_none();}'),
            'a{color:#fff}\n',
        )

    def test_true(self):
        self.assertEqual(
            compile_with_func('a { content: returns_true(); }'),
            'a{content:true}\n',
        )

    def test_false(self):
        self.assertEqual(
            compile_with_func('a { content: returns_false(); }'),
            'a{content:false}\n',
        )

    def test_unicode(self):
        self.assertEqual(
            compile_with_func('a { content: returns_unicode(); }'),
            u'\ufeffa{content:☃}\n',
        )

    def test_bytes(self):
        self.assertEqual(
            compile_with_func('a { content: returns_bytes(); }'),
            u'\ufeffa{content:☃}\n',
        )

    def test_number(self):
        self.assertEqual(
            compile_with_func('a { width: returns_number(); }'),
            'a{width:5px}\n',
        )

    def test_color(self):
        self.assertEqual(
            compile_with_func('a { color: returns_color(); }'),
            'a{color:rgba(1,2,3,0.5)}\n',
        )

    def test_comma_list(self):
        self.assertEqual(
            compile_with_func('a { font-family: returns_comma_list(); }'),
            'a{font-family:Arial,sans-serif}\n',
        )

    def test_space_list(self):
        self.assertEqual(
            compile_with_func('a { border-right: returns_space_list(); }'),
            'a{border-right:medium none}\n',
        )

    def test_bracketed_list(self):
        self.assertEqual(
            compile_with_func('a { content: returns_bracketed_list(); }'),
            'a{content:[hello ohai]}\n'
        )

    def test_py_dict(self):
        self.assertEqual(
            compile_with_func(
                'a { content: map-get(returns_py_dict(), foo); }',
            ),
            'a{content:bar}\n',
        )

    def test_map(self):
        self.assertEqual(
            compile_with_func(
                'a { content: map-get(returns_map(), foo); }',
            ),
            'a{content:bar}\n',
        )

    def test_identity_none(self):
        self.assertEqual(
            compile_with_func(
                'a {color: #fff; content: identity(returns_none());}',
            ),
            'a{color:#fff}\n',
        )

    def test_identity_true(self):
        self.assertEqual(
            compile_with_func('a { content: identity(returns_true()); }'),
            'a{content:true}\n',
        )

    def test_identity_false(self):
        self.assertEqual(
            compile_with_func('a { content: identity(returns_false()); }'),
            'a{content:false}\n',
        )

    def test_identity_strings(self):
        self.assertEqual(
            compile_with_func('a { content: identity(returns_unicode()); }'),
            u'\ufeffa{content:☃}\n',
        )

    def test_identity_number(self):
        self.assertEqual(
            compile_with_func('a { width: identity(returns_number()); }'),
            'a{width:5px}\n',
        )

    def test_identity_color(self):
        self.assertEqual(
            compile_with_func('a { color: identity(returns_color()); }'),
            'a{color:rgba(1,2,3,0.5)}\n',
        )

    def test_identity_comma_list(self):
        self.assertEqual(
            compile_with_func(
                'a { font-family: identity(returns_comma_list()); }',
            ),
            'a{font-family:Arial,sans-serif}\n',
        )

    def test_identity_space_list(self):
        self.assertEqual(
            compile_with_func(
                'a { border-right: identity(returns_space_list()); }',
            ),
            'a{border-right:medium none}\n',
        )

    def test_identity_bracketed_list(self):
        self.assertEqual(
            compile_with_func(
                'a { content: identity(returns_bracketed_list()); }',
            ),
            'a{content:[hello ohai]}\n',
        )

    def test_identity_py_dict(self):
        self.assertEqual(
            compile_with_func(
                'a { content: map-get(identity(returns_py_dict()), foo); }',
            ),
            'a{content:bar}\n',
        )

    def test_identity_map(self):
        self.assertEqual(
            compile_with_func(
                'a { content: map-get(identity(returns_map()), foo); }',
            ),
            'a{content:bar}\n',
        )

    def test_list_with_map_item(self):
        self.assertEqual(
            compile_with_func(
                'a{content: '
                'map-get(nth(identity(((foo: bar), (baz: womp))), 1), foo)'
                '}'
            ),
            'a{content:bar}\n'
        )

    def test_map_with_map_key(self):
        self.assertEqual(
            compile_with_func(
                'a{content: map-get(identity(((foo: bar): baz)), (foo: bar))}',
            ),
            'a{content:baz}\n',
        )


def test_stack_trace_formatting():
    try:
        sass.compile(string=u'a{☃')
        raise AssertionError('expected to raise CompileError')
    except sass.CompileError:
        tb = traceback.format_exc()
    assert tb.endswith(
        'CompileError: Error: Invalid CSS after "a{☃": expected "{", was ""\n'
        '        on line 1 of stdin\n'
        '>> a{☃\n'
        '   --^\n\n'
    )


def test_source_comments():
    out = sass.compile(string='a{color: red}', source_comments=True)
    assert out == '/* line 1, stdin */\na {\n  color: red; }\n'


def test_sassc_sourcemap(tmpdir):
    src_file = tmpdir.join('src').ensure_dir().join('a.scss')
    out_file = tmpdir.join('a.scss.css')
    out_map_file = tmpdir.join('a.scss.css.map')

    src_file.write('.c { font-size: 5px + 5px; }')

    exit_code = sassc.main([
        'sassc', '-m', src_file.strpath, out_file.strpath,
    ])
    assert exit_code == 0

    contents = out_file.read()
    assert contents == (
        '.c {\n'
        '  font-size: 10px; }\n'
        '\n'
        '/*# sourceMappingURL=a.scss.css.map */'
    )
    source_map_json = json.loads(out_map_file.read())
    assert source_map_json == {
        'sources': ['src/a.scss'],
        'version': 3,
        'names': [],
        'file': 'a.scss.css',
        'mappings': 'AAAA,AAAA,EAAE,CAAC;EAAE,SAAS,EAAE,IAAS,GAAI',
    }


def test_imports_from_cwd(tmpdir):
    scss_dir = tmpdir.join('scss').ensure_dir()
    scss_dir.join('_variables.scss').ensure()
    main_scss = scss_dir.join('main.scss')
    main_scss.write("@import 'scss/variables';")
    with tmpdir.as_cwd():
        out = sass.compile(filename=main_scss.strpath)
        assert out == ''


def test_import_no_css(tmpdir):
    tmpdir.join('other.css').write('body {color: green}')
    main_scss = tmpdir.join('main.scss')
    main_scss.write("@import 'other';")
    with pytest.raises(sass.CompileError):
        sass.compile(filename=main_scss.strpath)


@pytest.mark.parametrize('exts', [
    ('.css',),
    ['.css'],
    ['.foobar', '.css'],
])
def test_import_css(exts, tmpdir):
    tmpdir.join('other.css').write('body {color: green}')
    main_scss = tmpdir.join('main.scss')
    main_scss.write("@import 'other';")
    out = sass.compile(
        filename=main_scss.strpath,
        custom_import_extensions=exts,
    )
    assert out == 'body {\n  color: green; }\n'


@pytest.mark.parametrize('exts', [
    ['.css', 3],
    '.css',
    [b'.css'],
])
def test_import_css_error(exts, tmpdir):
    tmpdir.join('other.css').write('body {color: green}')
    main_scss = tmpdir.join('main.scss')
    main_scss.write("@import 'other';")
    with pytest.raises(TypeError):
        sass.compile(
            filename=main_scss.strpath,
            custom_import_extensions=exts,
        )


def test_import_css_string(tmpdir):
    tmpdir.join('other.css').write('body {color: green}')
    with tmpdir.as_cwd():
        out = sass.compile(
            string="@import 'other';",
            custom_import_extensions=['.css'],
        )
    assert out == 'body {\n  color: green; }\n'


def test_import_ext_other(tmpdir):
    tmpdir.join('other.foobar').write('body {color: green}')
    main_scss = tmpdir.join('main.scss')
    main_scss.write("@import 'other';")
    out = sass.compile(
        filename=main_scss.strpath,
        custom_import_extensions=['.foobar'],
    )
    assert out == 'body {\n  color: green; }\n'
