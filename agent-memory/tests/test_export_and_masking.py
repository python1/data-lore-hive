import json
import unittest

from support import SAMPLE, SECRET, RunCase
import masking
import tg_export


class InventoryTest(unittest.TestCase):
    def test_inventory_counts_without_text(self):
        _, data, _ = tg_export.load(SAMPLE)
        chat = tg_export.inventory(data)['chats'][0]
        self.assertEqual(chat['counts']['records'], 17)
        self.assertEqual((chat['counts']['service'], chat['counts']['media'], chat['counts']['forwarded']), (1, 1, 1))
        self.assertEqual(set(chat['senders']), {'user1000001', 'user2000002'})
        self.assertNotIn('pottery', json.dumps(tg_export.inventory(data)))

    def test_entities_flatten_to_visible_text(self):
        _, data, _ = tg_export.load(SAMPLE)
        by_id = {m.message_id: m for m in tg_export.chat_messages(data, 0)}
        self.assertEqual(by_id[4].text, 'I prefer short answers in the morning and longer ones at night.')

    def test_duplicate_ids_are_refused(self):
        data = json.loads(SAMPLE.read_text())
        data['messages'][3]['id'] = data['messages'][2]['id']
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            tg_export.chat_messages(data, 0)

    def test_naive_date_alone_is_not_assumed_utc(self):
        dt, errors = tg_export.timestamp({'date': '2026-01-03T09:00:00'})
        self.assertIsNone(dt)
        self.assertIn('missing_absolute_timestamp', errors)

    def test_full_export_shape(self):
        data = json.loads(SAMPLE.read_text())
        self.assertEqual(len(tg_export.extract_chats({'chats': {'list': [data, data]}})), 2)


class MaskingTest(unittest.TestCase):
    def test_common_secret_forms_are_masked(self):
        for text in ('password: hunter2-example', 'api_key = sk-proj-abcdefghijklmnop',
                     'Authorization: Bearer abc.def.ghi', 'https://example.com/reset-password?token=abc',
                     '-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----'):
            masked, spans = masking.masked_outgoing(text, '2026-01-01')
            self.assertTrue(spans, text)
            self.assertIn('[SECRET: ', masked)
            self.assertFalse(masking.detected_unmasked(masked))

    def test_service_is_named_from_nearby_text(self):
        masked, _ = masking.masked_outgoing('my github token is ghp_abcdefghijklmnop1234', '2026-01-01')
        self.assertIn('for github', masked)

    def test_marker_itself_is_not_a_detection(self):
        self.assertEqual(masking.detected_unmasked(
            'x [SECRET: password for unspecified service, shared 2026-01-01] y'), [])
        self.assertTrue(masking.detected_unmasked('the password is swordfish99'))

    def test_ordinary_prose_is_left_alone(self):
        text = 'I prefer short answers in the morning and longer ones at night.'
        self.assertEqual(masking.masked_outgoing(text, '2026-01-01'), (text, []))


class RunMaskingTest(RunCase, unittest.TestCase):
    def test_labelled_and_repeated_secret_never_leaves(self):
        outgoing = ' '.join(text for text, _ in self.run.outgoing.values())
        self.assertNotIn(SECRET, outgoing)
        self.assertIn('Reminder for later: [SECRET: ', self.run.outgoing[16][0])

    def test_only_the_two_voices_own_text_is_used(self):
        # 1 service record, 11 photo caption, 14 forwarded from someone else.
        self.assertTrue({1, 11, 14}.isdisjoint(self.run.messages))
        self.assertEqual(len(self.run.messages), 14)

    def test_changed_export_is_refused(self):
        self.export.write_bytes(self.export.read_bytes() + b'\n')
        import pipeline
        with self.assertRaisesRegex(ValueError, 'export changed'):
            pipeline.Run(self.root)


if __name__ == '__main__':
    unittest.main()
