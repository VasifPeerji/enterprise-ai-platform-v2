/**
 * V07 conversation export — serialise a conversation to clean Markdown and
 * trigger a download. Operates on the same typed content-block array the
 * renderer uses, so tables, prose and source lists survive the round-trip.
 */

function tableToMarkdown(block) {
  const headers = block.headers || [];
  const rows = block.rows || [];
  if (!headers.length) return '';
  const head = `| ${headers.join(' | ')} |`;
  const sep = `| ${headers.map(() => '---').join(' | ')} |`;
  const body = rows.map((r) => `| ${(r || []).join(' | ')} |`).join('\n');
  return [head, sep, body].filter(Boolean).join('\n');
}

function blockToMarkdown(block) {
  if (!block) return '';
  switch (block.type) {
    case 'text':
      return (block.text || '').trim();
    case 'table':
      return tableToMarkdown(block);
    case 'web_sources':
      return (
        '**Sources**\n' +
        (block.sources || [])
          .map((s) => `${s.n}. [${s.title || s.url}](${s.url})`)
          .join('\n')
      );
    case 'citations':
      return (
        '**Sources**\n' +
        (block.pageProofs || [])
          .map((p, i) => `${i + 1}. ${p.title || 'Source'} — page ${p.page_number ?? '—'}`)
          .join('\n')
      );
    case 'attachments':
      return (block.files || []).map((f) => `📎 _${f.name}_`).join('  ');
    case 'web_search_indicator':
      return '_searched the web_';
    // Charts are derived from tables/prose already exported; media/widgets are
    // interactive and have no clean Markdown form — skip them.
    default:
      return '';
  }
}

/** Serialise a whole conversation to a Markdown document string. */
export function conversationToMarkdown(conv) {
  if (!conv) return '';
  const out = [`# ${conv.title || 'Conversation'}`, ''];
  if (conv.createdAt) {
    out.push(`_Exported from V07 · ${new Date().toLocaleString()}_`, '');
  }
  for (const m of conv.messages || []) {
    const who =
      m.role === 'user'
        ? '🧑 You'
        : m.model?.name
          ? `🤖 Assistant · ${m.model.name}`
          : '🤖 Assistant';
    out.push(`---`, '', `### ${who}`, '');
    for (const b of m.content || []) {
      const md = blockToMarkdown(b);
      if (md) out.push(md, '');
    }
  }
  return out.join('\n').trim() + '\n';
}

/** Build a filesystem-safe filename stem from a conversation title. */
function safeName(title) {
  const base = (title || 'conversation')
    .replace(/[^\w\- ]+/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 50);
  return base || 'conversation';
}

/** Serialise + download a conversation as `<title>.md`. Returns the filename. */
export function downloadConversationMarkdown(conv) {
  const md = conversationToMarkdown(conv);
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const filename = `${safeName(conv?.title)}.md`;
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 200);
  return filename;
}
