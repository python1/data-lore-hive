import unittest

from support import RunCase
import quotes

ALL = set(range(1, 18))


def proposal(statement, *evidence, supersedes=(), category='identity', topic='topic'):
    return {'category': category, 'topic': topic, 'statement': statement,
            'evidence': [{'message_id': m, 'quote': q} for m, q in evidence],
            'supersedes_message_ids': list(supersedes)}


class QuoteVerificationTest(RunCase, unittest.TestCase):
    def verify(self, p, role='user', visible=ALL):
        return quotes.verify_proposal(p, role, self.run, visible)

    def test_exact_quote_is_cited_with_offsets(self):
        record = self.verify(proposal('Juniper teaches pottery.', (2, 'I teach pottery in a small studio')))
        cite = record['evidence'][0]
        self.assertEqual(self.run.messages[2].text[cite['start']:cite['end']], 'I teach pottery in a small studio')
        self.assertEqual(record['record_id'], quotes.record_id('user', 'Juniper teaches pottery.'))

    def test_quote_across_formatting_entities_is_exact(self):
        record = self.verify(proposal('Juniper prefers short morning answers.', (4, 'I prefer short answers in the morning')))
        self.assertEqual(record['evidence'][0]['start'], 0)

    def test_no_repair(self):
        for quote in ('I teach  pottery', 'i teach pottery', 'I teach pottery...', 'I teach pottery by the river'):
            with self.subTest(quote=quote), self.assertRaisesRegex(ValueError, 'word for word|shown'):
                self.verify(proposal('Juniper teaches pottery.', (2, quote)))

    def test_voices_are_never_merged(self):
        with self.assertRaisesRegex(ValueError, 'other voice'):
            self.verify(proposal('Juniper wants to be careful.', (3, 'I want to be a careful, honest helper')))
        with self.assertRaisesRegex(ValueError, 'required voice'):
            self.verify(proposal('Wren wants to be careful.', (3, 'I want to be a careful, honest helper')), 'agent')
        with self.assertRaisesRegex(ValueError, 'required voice'):
            self.verify(proposal('She teaches pottery.', (2, 'I teach pottery')))
        record = self.verify(proposal('I want to be a careful, honest helper.',
                                      (3, 'I want to be a careful, honest helper')), 'agent')
        self.assertEqual(record['role'], 'agent')

    def test_out_of_chunk_and_excluded_messages(self):
        with self.assertRaisesRegex(ValueError, 'out-of-chunk'):
            self.verify(proposal('Juniper teaches pottery.', (2, 'I teach pottery')), visible={3, 4})
        with self.assertRaisesRegex(ValueError, 'out-of-chunk'):
            self.verify(proposal('Juniper knows glazes mature at 1220.', (14, 'Cone 6 glazes mature')))

    def test_secrets_cannot_be_quoted(self):
        with self.assertRaisesRegex(ValueError, 'masked quote'):
            self.verify(proposal('Juniper shared a password.', (8, 'password is [SECRET: credential')))
        with self.assertRaisesRegex(ValueError, 'shown'):
            self.verify(proposal('Juniper has a wifi password.', (8, 'password is kiln-glaze-4471')))
        with self.assertRaisesRegex(ValueError, 'secret'):
            self.verify(proposal('Juniper said the password is hunter22.', (2, 'I teach pottery')))

    def test_supersession_must_be_earlier_and_same_voice(self):
        record = self.verify(proposal('Juniper asked for English again after asking for French.',
                                      (9, 'Please answer me in English again.'), supersedes=[6]))
        self.assertEqual(record['supersedes'][0]['message_id'], 6)
        with self.assertRaisesRegex(ValueError, 'not earlier'):
            self.verify(proposal('Juniper asked for French.', (6, 'always answer me in French'), supersedes=[9]))
        with self.assertRaisesRegex(ValueError, 'same voice'):
            self.verify(proposal('Juniper asked for English.', (9, 'Please answer me in English again.'), supersedes=[7]))

    def test_recheck_detects_any_edit(self):
        record = self.verify(proposal('Juniper teaches pottery.', (2, 'I teach pottery')))
        quotes.recheck(record, self.run)
        for field, value in (('statement', 'Juniper teaches sculpture.'), ('role', 'agent')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                quotes.recheck({**record, field: value}, self.run)
        moved = {**record, 'evidence': [{**record['evidence'][0], 'start': 1}]}
        with self.assertRaisesRegex(ValueError, 'no longer matches'):
            quotes.recheck(moved, self.run)


if __name__ == '__main__':
    unittest.main()
