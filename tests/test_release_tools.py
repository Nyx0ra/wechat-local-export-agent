import hashlib
import importlib.util
import pathlib
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(test, name):
    path = ROOT / 'tools' / (name + '.py')
    test.assertTrue(path.is_file(), name + ' is not implemented')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseToolsTests(unittest.TestCase):
    def test_privacy_scan_rejects_runtime_data_and_user_paths(self):
        module = load(self, 'privacy_check')
        with tempfile.TemporaryDirectory(prefix='wx-public-scan-') as temp:
            root = pathlib.Path(temp)
            (root / 'scripts').mkdir()
            (root / 'scripts/clean.py').write_text('print("synthetic")\n', encoding='utf-8')
            self.assertEqual(module.scan(root), [])
            (root / 'scripts/personal.py').write_text('location = "' + 'C:' + '/Users/' + 'fictional-user' + '/private"', encoding='utf-8')
            (root / 'case-config.json').write_text('{}', encoding='utf-8')
            (root / 'messages.sqlite').write_bytes(b'synthetic bytes')
            findings = module.scan(root)
            self.assertGreaterEqual(len(findings), 3)

    def test_private_deny_terms_not_printed(self):
        module = load(self, 'privacy_check')
        with tempfile.TemporaryDirectory(prefix='wx-public-scan-') as temp:
            root = pathlib.Path(temp)
            (root / 'README.md').write_text('PRIVATE_' + 'SENTINEL', encoding='utf-8')
            findings = module.scan(root, ['PRIVATE_' + 'SENTINEL'])
            self.assertEqual(len(findings), 1)
            self.assertNotIn('PRIVATE_' + 'SENTINEL', str(findings))

    def test_archive_install_hash_and_traversal(self):
        module = load(self, 'fetch_upstream')
        with tempfile.TemporaryDirectory(prefix='wx-upstream-') as temp:
            root = pathlib.Path(temp)
            archive = root / 'tool.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('WechatExporterCmd.exe', b'synthetic executable placeholder')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            exe_digest = hashlib.sha256(b'synthetic executable placeholder').hexdigest()
            module.install_archive(archive, root / 'ok', digest, exe_digest)
            self.assertTrue((root / 'ok/WechatExporterCmd.exe').is_file())
            with self.assertRaises(ValueError):
                module.install_archive(archive, root / 'bad-hash', '0' * 64, exe_digest)
            for unsafe in ('../escape', 'C:/escape', '/escape', '..\\escape'):
                with zipfile.ZipFile(archive, 'w') as output:
                    output.writestr(unsafe, b'bad')
                with self.subTest(name=unsafe), self.assertRaises(ValueError):
                    module.install_archive(archive, root / 'unsafe', hashlib.sha256(archive.read_bytes()).hexdigest(), exe_digest)
            self.assertFalse((root / 'escape').exists())
