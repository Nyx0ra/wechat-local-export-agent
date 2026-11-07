import pathlib
import tempfile
import unittest
import zstandard
from scripts.common import decode_body, exporter_for
import json


class CompressionTests(unittest.TestCase):
    def test_unpinned_native_executable_rejected(self):
        with tempfile.TemporaryDirectory(prefix='wx-native-pin-') as temp:
            root = pathlib.Path(temp)
            exe = root / 'fake.exe'
            exe.write_bytes(b'synthetic untrusted program')
            (root / 'case-config.json').write_text(json.dumps({'backup_dir': str(root / 'backup'), 'exporter_executable': str(exe)}), encoding='utf-8')
            with self.assertRaises(ValueError):
                exporter_for(root)

    def test_plaintext_and_missing_dictionary(self):
        self.assertEqual(decode_body('synthetic text', 0, {}), ('synthetic text', None))
        frame = zstandard.ZstdCompressor().compress(b'synthetic text')
        self.assertEqual(decode_body(frame, 2, {}), (None, 0))

    def test_unsupported_encoding_rejected(self):
        for value, flag in [(b'not-a-frame', 2), (b'not-a-frame', 0), (None, 0)]:
            with self.assertRaises(ValueError):
                decode_body(value, flag, {})

    def test_matching_and_wrong_dictionary(self):
        samples = [(f'Synthetic repeated conversation text item {i} ' * 12).encode() for i in range(80)]
        dictionary = zstandard.train_dictionary(1024, samples)
        frame = zstandard.ZstdCompressor(dict_data=dictionary).compress(b'Synthetic repeated conversation text item 42')
        with tempfile.TemporaryDirectory(prefix='wx-dict-') as temp:
            path = pathlib.Path(temp) / 'synthetic.dict'
            path.write_bytes(dictionary.as_bytes())
            options = {'zstd_dictionaries': {str(dictionary.dict_id()): str(path)}}
            self.assertEqual(decode_body(frame, 2, options)[0], 'Synthetic repeated conversation text item 42')
            wrong = zstandard.train_dictionary(1024, [b'Another artificial data sample ' + item for item in samples])
            path.write_bytes(wrong.as_bytes())
            with self.assertRaises(ValueError):
                decode_body(frame, 2, options)
