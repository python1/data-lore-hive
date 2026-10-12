// Claude export adapter: conversations.json is an array of conversations, each with a
// `chat_messages` list ({ uuid, sender, text, content: [blocks], created_at }). Text blocks
// make the message; a non-empty thinking block becomes its own 'reasoning' message; tool,
// flag and token-budget blocks are skipped; image and document blocks count as attachments.
// injected_prompt_block is text the app added to a turn, not something the person wrote: it
// is never used, and neither is the message's plain `text` when content blocks exist (it can
// echo an injected prompt). Every message has `parent_message_uuid` (checked October 2026 with
// tools/export-shape.mjs), so messages form a tree and the current thread is the path to the
// most recent message. Anything unexpected becomes a warning.
import { isObject, pushMessage, utcDate } from './export-common.mjs';

export const detectClaude = (first) => isObject(first) && Array.isArray(first.chat_messages);

const ROLES = { human: 'user', assistant: 'agent' };
const has = (o, k) => typeof k === 'string' && Object.hasOwn(o, k);
const SKIP_BLOCKS = new Set(['tool_use', 'tool_result', 'server_tool_use', 'web_search_tool_result', 'flag', 'token_budget']);
const ATTACHMENT_BLOCKS = new Set(['image', 'document', 'file']);

/** -> { text, thinking, attachments } from one message's content blocks (or its legacy `text`). */
function readBlocks(message, warn) {
  const texts = [], thoughts = [];
  let attachments = (Array.isArray(message.attachments) ? message.attachments.length : 0) + (Array.isArray(message.files) ? message.files.length : 0);
  const blocks = Array.isArray(message.content) ? message.content : [];
  for (const block of blocks) {
    const type = isObject(block) && typeof block.type === 'string' ? block.type : '(missing)';
    if (type === 'text' && typeof block.text === 'string') texts.push(block.text);
    else if (type === 'thinking' && typeof block.thinking === 'string' && block.thinking.trim()) thoughts.push(block.thinking);
    else if (type === 'thinking') warn('skipped-hidden-thinking');
    else if (type === 'injected_prompt_block') warn('skipped-injected-prompt');
    else if (SKIP_BLOCKS.has(type)) warn('skipped-content-type', type);
    else if (ATTACHMENT_BLOCKS.has(type)) attachments++;
    else warn('unknown-content-type', type);
  }
  // Older exports carry the text only in `text`. Once a message has content blocks, `text` is
  // never used: for a turn made of an injected_prompt_block it holds the injected prompt.
  const text = texts.length ? texts.join('\n\n') : blocks.length ? '' : typeof message.text === 'string' ? message.text : '';
  return { text, thinking: thoughts.join('\n\n'), attachments };
}

/** Message indexes in display order and the set on the current path. */
function threadOrder(list, warn) {
  const all = list.map((_, i) => i);
  const byId = new Map(list.map((m, i) => [m.uuid, i]));
  const tree = list.length > 0 && list.every((m) => typeof m.uuid === 'string' && typeof m.parent_message_uuid === 'string') && byId.size === list.length;
  if (!tree) return { order: all, current: new Set(all) };
  const children = new Map();
  const roots = [];
  list.forEach((m, i) => {
    if (byId.has(m.parent_message_uuid) && m.parent_message_uuid !== m.uuid) {
      if (!children.has(m.parent_message_uuid)) children.set(m.parent_message_uuid, []);
      children.get(m.parent_message_uuid).push(i);
    } else roots.push(i);
  });
  const time = (i) => Date.parse(list[i].created_at) || 0;
  const order = [], seen = new Set();
  const stack = [...roots].reverse();
  while (stack.length) {
    const i = stack.pop();
    if (seen.has(i)) continue;
    seen.add(i); order.push(i);
    const kids = [...(children.get(list[i].uuid) ?? [])].sort((a, b) => time(a) - time(b) || a - b);
    for (let k = kids.length - 1; k >= 0; k--) stack.push(kids[k]);
  }
  if (order.length !== list.length) { warn('unreachable-nodes'); order.push(...all.filter((i) => !seen.has(i))); }
  // Current thread: from the most recent message (last in list order on ties) back to its root.
  let leaf = 0;
  for (const i of all) if (time(i) >= time(leaf)) leaf = i;
  const current = new Set();
  for (let i = leaf; i !== undefined && !current.has(i); i = byId.get(list[i].parent_message_uuid)) current.add(i);
  return { order, current };
}

export function parseClaude(json, warn) {
  const conversations = [];
  json.forEach((conv, index) => {
    if (!isObject(conv) || !Array.isArray(conv.chat_messages)) { warn('skipped-conversation-without-messages'); return; }
    const id = typeof conv.uuid === 'string' ? conv.uuid : `#${index + 1}`;
    const list = conv.chat_messages.filter(isObject);
    const { order, current } = threadOrder(list, warn);
    const messages = [];
    for (const i of order) {
      const m = list[i];
      if (!has(ROLES, m.sender)) { warn('skipped-role', typeof m.sender === 'string' ? m.sender : '(missing)'); continue; }
      const key = `${id}/${typeof m.uuid === 'string' ? m.uuid : `#${i + 1}`}`;
      const date = utcDate(m.created_at);
      const { text, thinking, attachments } = readBlocks(m, warn);
      const base = { conversationId: id, role: ROLES[m.sender], date, current: current.has(i) };
      // Thinking happened before the reply, so it is listed first.
      if (thinking.trim()) pushMessage(messages, warn, { ...base, key: `${key}#thinking`, kind: 'reasoning', text: thinking, attachments: 0 });
      pushMessage(messages, warn, { ...base, key, kind: 'text', text, attachments });
    }
    if (!messages.length) { warn('skipped-empty-conversation'); return; }
    conversations.push({ id, title: typeof conv.name === 'string' ? conv.name : '', date: utcDate(conv.created_at), messages });
  });
  return conversations;
}
