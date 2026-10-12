// ChatGPT export adapter: conversations.json is an array of conversations, each a tree of
// nodes in `mapping` ({ id, message, parent, children }). The thread the person saw is the
// path from `current_node` up to the root; other branches are regenerations and edits.
// Field names here were taken from public descriptions of the format and must be checked
// against real exports with tools/export-shape.mjs; anything unexpected becomes a warning.
import { isObject, pushMessage, utcDate } from './export-common.mjs';

export const detectChatGPT = (first) => isObject(first) && isObject(first.mapping);

const ROLES = { user: 'user', assistant: 'agent' };
// Content types that are context or tool plumbing rather than something said in the chat.
const SKIP_TYPES = new Set(['user_editable_context', 'model_editable_context', 'execution_output', 'tether_browsing_display',
  'tether_quote', 'system_error', 'sonic_webpage', 'computer_output', 'super_widget']);

const has = (o, k) => typeof k === 'string' && Object.hasOwn(o, k);
const strings = (parts) => (Array.isArray(parts) ? parts : []).filter((p) => typeof p === 'string');

/** -> { kind, text, attachments } or null to skip (after warning). */
function readContent(content, warn) {
  const type = isObject(content) && typeof content.content_type === 'string' ? content.content_type : '(missing)';
  const objects = isObject(content) && Array.isArray(content.parts) ? content.parts.filter(isObject) : [];
  switch (type) {
    case 'text':
      return { kind: 'text', text: strings(content.parts).join('\n\n'), attachments: objects.length };
    case 'multimodal_text': {
      // Voice messages carry their transcript as an object part; images and audio files are attachments.
      const parts = Array.isArray(content.parts) ? content.parts : [];
      const pieces = parts.map((p) => typeof p === 'string' ? p : isObject(p) && p.content_type === 'audio_transcription' && typeof p.text === 'string' ? p.text : null);
      const attachments = parts.filter((p) => isObject(p) && p.content_type !== 'audio_transcription').length;
      return { kind: 'text', text: pieces.filter((p) => p !== null).join('\n\n'), attachments };
    }
    case 'code':
      return { kind: 'code', text: typeof content.text === 'string' ? content.text : '', attachments: 0 };
    case 'thoughts':
      return { kind: 'reasoning', text: (Array.isArray(content.thoughts) ? content.thoughts : []).map((t) => isObject(t) && typeof t.content === 'string' ? t.content : '').filter(Boolean).join('\n\n'), attachments: 0 };
    case 'reasoning_recap':
      return { kind: 'reasoning', text: typeof content.content === 'string' ? content.content : '', attachments: 0 };
    default:
      if (SKIP_TYPES.has(type)) { warn('skipped-content-type', type); return null; }
      warn('unknown-content-type', type);
      if (isObject(content) && strings(content.parts).length) return { kind: 'other', text: strings(content.parts).join('\n\n'), attachments: objects.length };
      if (isObject(content) && typeof content.text === 'string') return { kind: 'other', text: content.text, attachments: 0 };
      return null;
  }
}

/** Node ids in display order (depth first, children in export order), plus the set on the current path. */
function walkTree(mapping, currentNode, warn) {
  const ids = Object.keys(mapping);
  const roots = ids.filter((id) => !isObject(mapping[id]) || !has(mapping, mapping[id].parent) || mapping[id].parent === id);
  const order = [], seen = new Set();
  const stack = [...roots].reverse();
  while (stack.length) {
    const id = stack.pop();
    if (seen.has(id) || !has(mapping, id)) continue;
    seen.add(id); order.push(id);
    const children = isObject(mapping[id]) && Array.isArray(mapping[id].children) ? mapping[id].children : [];
    for (let i = children.length - 1; i >= 0; i--) stack.push(children[i]);
  }
  const orphans = ids.filter((id) => !seen.has(id));
  if (orphans.length) { warn('unreachable-nodes'); order.push(...orphans); }

  let leaf = currentNode;
  if (!has(mapping, leaf)) {
    // No usable current_node: follow the last child from the first root, i.e. the latest branch.
    warn('missing-current-node');
    leaf = roots[0];
    const guard = new Set();
    while (leaf !== undefined && !guard.has(leaf)) {
      guard.add(leaf);
      const children = isObject(mapping[leaf]) && Array.isArray(mapping[leaf].children) ? mapping[leaf].children.filter((c) => has(mapping, c)) : [];
      if (!children.length) break;
      leaf = children[children.length - 1];
    }
  }
  const current = new Set();
  for (let id = leaf; has(mapping, id) && !current.has(id); id = isObject(mapping[id]) ? mapping[id].parent : undefined) current.add(id);
  return { order, current };
}

export function parseChatGPT(json, warn) {
  const conversations = [];
  json.forEach((conv, index) => {
    if (!isObject(conv) || !isObject(conv.mapping)) { warn('skipped-conversation-without-messages'); return; }
    const id = typeof conv.id === 'string' ? conv.id : typeof conv.conversation_id === 'string' ? conv.conversation_id : `#${index + 1}`;
    const { order, current } = walkTree(conv.mapping, conv.current_node, warn);
    const messages = [];
    for (const nodeId of order) {
      const message = isObject(conv.mapping[nodeId]) ? conv.mapping[nodeId].message : null;
      if (!isObject(message)) continue; // structural node (the root), no message
      const role = isObject(message.author) ? message.author.role : undefined;
      if (!has(ROLES, role)) { warn('skipped-role', typeof role === 'string' ? role : '(missing)'); continue; }
      if (isObject(message.metadata) && message.metadata.is_visually_hidden_from_conversation === true) { warn('skipped-hidden-message'); continue; }
      if (role === 'assistant' && typeof message.recipient === 'string' && message.recipient !== 'all') { warn('skipped-tool-call', message.recipient); continue; }
      const content = readContent(message.content, warn);
      if (!content) continue;
      pushMessage(messages, warn, {
        key: `${id}/${nodeId}`, conversationId: id, role: ROLES[role], kind: content.kind,
        date: utcDate(message.create_time), text: content.text, current: current.has(nodeId), attachments: content.attachments
      });
    }
    if (!messages.length) { warn('skipped-empty-conversation'); return; }
    conversations.push({ id, title: typeof conv.title === 'string' ? conv.title : '', date: utcDate(conv.create_time), messages });
  });
  return conversations;
}
