// Invented fixtures: the fictional Larkfield community garden. No real people or chats.
// Shapes follow tools/export-shape.mjs output; regenerate with: node test/fixtures/make-fixtures.mjs test/fixtures
import { writeFileSync } from 'node:fs';
const out = process.argv[2];
if (!out) { console.error('Usage: node test/fixtures/make-fixtures.mjs OUT_DIR'); process.exit(1); }
const t = (iso) => Date.parse(iso) / 1000;
const u = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
function chain(nodes) { // nodes: [id, parent, message|null]; children derived in listed order
  const mapping = {};
  for (const [id, parent, message] of nodes) mapping[id] = { id, message, parent, children: [] };
  for (const [id, parent] of nodes) if (parent && mapping[parent]) mapping[parent].children.push(id);
  return mapping;
}
const msg = (id, role, created, content, extra = {}) => ({ id, author: { role, name: null, metadata: {} }, create_time: created === null ? null : t(created), update_time: null,
  content, status: 'finished_successfully', end_turn: role === 'assistant' ? true : null, weight: 1, metadata: {}, recipient: 'all', channel: null, ...extra });
const text = (...parts) => ({ content_type: 'text', parts });

const chatgpt = [
  { title: 'Seed swap plans', create_time: t('2026-03-02T08:15:00Z'), update_time: t('2026-03-02T09:00:00Z'), id: u(1001), conversation_id: u(1001),
    current_node: u(18), default_model_slug: 'gpt-example', is_archived: false,
    mapping: chain([
      ['client-created-root', null, null],
      [u(11), 'client-created-root', msg(u(11), 'system', null, text(''), { weight: 0, metadata: { is_visually_hidden_from_conversation: true } })],
      [u(12), u(11), msg(u(12), 'user', null, { content_type: 'user_editable_context', user_profile: 'Invented profile.', user_instructions: 'Invented instructions.' }, { metadata: { is_visually_hidden_from_conversation: true } })],
      [u(13), u(12), msg(u(13), 'user', '2026-03-02T08:15:00Z', text('Morning! I look after the tomato beds at the Larkfield community garden. Can you help me plan the seed swap?'))],
      [u(14), u(13), msg(u(14), 'assistant', '2026-03-02T08:15:20Z', text('Sure. Draft one: hold the swap sometime in April.'))],
      [u(15), u(13), msg(u(15), 'assistant', '2026-03-02T08:16:00Z', text("Happy to help, Rowan. Let's hold the seed swap on the first Saturday in April."), { metadata: { model_slug: 'gpt-example' } })],
      [u(16), u(15), msg(u(16), 'user', '2026-03-02T08:20:00Z', text('Can we do it by the shed?'))],
      [u(17), u(16), msg(u(17), 'assistant', '2026-03-02T08:20:10Z', text('Yes, by the shed works.'))],
      [u(19), u(15), msg(u(19), 'user', '2026-03-02T08:21:00Z', text('Can we do it by the greenhouse instead? The shed code changed.'))],
      [u(18), u(19), msg(u(18), 'assistant', '2026-03-02T08:21:30.250Z', text("The greenhouse is a good spot. I'll note that the shed code changed."))]
    ]) },
  { title: 'Shed rota', create_time: t('2026-03-09T18:00:00Z'), update_time: null, id: u(1002), current_node: u(32),
    mapping: chain([
      ['root-b', null, null],
      [u(21), 'root-b', msg(u(21), 'user', '2026-03-09T18:00:00Z', { content_type: 'multimodal_text', parts: [
        { content_type: 'image_asset_pointer', asset_pointer: 'file-service://file-invented-0001', size_bytes: 1234, width: 640, height: 480 },
        'Here is the rota photo. Ivy waters on Mondays 🌱, Rowan on Thursdays.'] })],
      [u(22), u(21), msg(u(22), 'assistant', '2026-03-09T18:00:05Z', { content_type: 'code', language: 'python', text: "rota = {'Mon': 'Ivy'}" }, { recipient: 'python' })],
      [u(23), u(22), msg(u(23), 'tool', '2026-03-09T18:00:06Z', { content_type: 'execution_output', text: "{'Mon': 'Ivy'}" }, { author: { role: 'tool', name: 'python', metadata: {} } })],
      [u(24), u(23), msg(u(24), 'assistant', '2026-03-09T18:00:07Z', { content_type: 'thoughts', thoughts: [{ summary: 'Reading the rota', content: 'The photo lists two people and two days.' }], source_analysis_msg_id: u(23) })],
      [u(25), u(24), msg(u(25), 'assistant', '2026-03-09T18:00:08Z', { content_type: 'reasoning_recap', content: 'Thought for 4 seconds' })],
      [u(26), u(25), msg(u(26), 'assistant', '2026-03-09T18:00:10Z', text('Rota:\r\n- Ivy: Mondays\r\n- Rowan: Thursdays\r\nThe cafe\u0301 opens at 9. Water early, water deeply, water early.'))],
      [u(27), u(26), msg(u(27), 'user', null, { content_type: 'multimodal_text', parts: [
        { content_type: 'audio_transcription', text: 'Thanks, that matches what I said on the phone.', direction: 'in' },
        { content_type: 'audio_asset_pointer', asset_pointer: 'sediment://file-invented-0002', size_bytes: 999 }] })],
      [u(28), u(27), msg(u(28), 'assistant', '2026-03-09T18:01:00Z', { content_type: 'future_widget', parts: ["A widget type this page doesn't know yet."] })],
      [u(29), u(28), msg(u(29), 'assistant', '2026-03-09T18:01:10Z', { content_type: 'code', language: 'python', text: "print('water early')" })],
      [u(30), u(29), msg(u(30), 'user', '2026-03-09T18:02:00Z', text('Odd byte here: \ud800 end.'))],
      [u(31), u(30), msg(u(31), 'assistant', '2026-03-09T18:02:05Z', { content_type: 'hologram' })],
      [u(32), u(31), msg(u(32), 'user', '2026-03-09T18:03:00Z', text('   '))]
    ]) },
  { title: 'Empty chat', create_time: t('2026-03-10T10:00:00Z'), id: u(1003), current_node: 'root-c', mapping: chain([['root-c', null, null]]) },
  { title: 'Compost day', create_time: t('2026-03-12T07:30:00Z'), id: u(1004), current_node: null,
    mapping: chain([
      ['root-d', null, null],
      [u(41), 'root-d', msg(u(41), 'user', '2026-03-12T07:30:00Z', text('The compost bins get turned on the first of the month.'))],
      [u(42), u(41), msg(u(42), 'assistant', '2026-03-12T07:30:04Z', text('Noted: compost on the first of each month.'))]
    ]) },
  { title: 'Broken conversation', id: u(1005) }
];

const block = (s) => ({ type: 'text', text: s, start_timestamp: null, stop_timestamp: null, citations: [] });
const cm = (n, sender, created, content, extra = {}) => ({ uuid: u(n), text: '', content, sender, created_at: created, updated_at: created, attachments: [], files: [], ...extra });
const claude = [
  { uuid: u(2001), name: 'Greenhouse watering', summary: '', created_at: '2026-03-06T17:00:00.123456Z', updated_at: '2026-03-06T18:00:00Z', account: { uuid: u(9999) },
    chat_messages: [
      cm(51, 'human', '2026-03-06T17:00:00.123456Z', [block('Who waters the greenhouse on Fridays?')],
        { attachments: [{ file_name: 'rota.txt', file_size: 12, file_type: 'txt', extracted_content: 'Fri: Tally' }] }),
      cm(52, 'assistant', '2026-03-06T17:00:05.5+00:00', [{ type: 'thinking', thinking: 'The rota file says Tally on Fridays.' }, block('According to the rota you shared, Tally waters the greenhouse on Fridays.')]),
      cm(53, 'human', '2026-03-06T19:00:00+02:00', [block('Great. Remind me: the compost bins get turned on the first of the month.')]),
      cm(54, 'assistant', '2026-03-06T17:00:20Z', [{ type: 'tool_use', name: 'web_search', input: { query: 'compost' } },
        { type: 'tool_result', content: [{ type: 'text', text: 'invented search result' }] }, block('Noted: compost bins are turned on the first of the month.'), { type: 'image', source: {} }]),
      { uuid: u(55), text: 'Legacy text only message about the café 🌻.', sender: 'human', created_at: '2026-03-06T17:01:00Z' },
      cm(56, 'assistant', '2026-03-06T17:01:05Z', [{ type: 'hologram', data: 'x' }]),
      cm(57, 'system', '2026-03-06T17:01:06Z', [block('system note')])
    ] },
  { uuid: u(2002), name: 'Regenerated answer', created_at: '2026-03-07T09:00:00Z',
    chat_messages: [
      cm(61, 'human', '2026-03-07T09:00:00Z', [block('Which bed gets the beans?')], { parent_message_uuid: u(0) }),
      cm(62, 'assistant', '2026-03-07T09:00:05Z', [block('Bed 3, I think.')], { parent_message_uuid: u(61) }),
      cm(63, 'assistant', '2026-03-07T09:02:00Z', [block('Bed 4 gets the beans; bed 3 is resting this year.')], { parent_message_uuid: u(61) }),
      cm(64, 'human', '2026-03-07T09:03:00Z', [block('Bed 4 it is.')], { parent_message_uuid: u(63) })
    ] },
  { uuid: u(2003), name: 'No messages field', created_at: '2026-03-08T09:00:00Z' },
  { uuid: u(2004), name: 'Empty list', created_at: '2026-03-08T10:00:00Z', chat_messages: [] }
];

writeFileSync(`${out}/chatgpt-conversations.json`, JSON.stringify(chatgpt, null, 1) + '\n');
writeFileSync(`${out}/claude-conversations.json`, JSON.stringify(claude, null, 1) + '\n');
