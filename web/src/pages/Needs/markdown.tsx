/**
 * Tiny, safe markdown-ish renderer for `Need.instructions_md` (no HTML injection: output is React nodes).
 * Supports paragraphs, `-`/`*`/`1.` lists, `#` headings, `| a | b |` tables, **bold**, *italic* / _italic_,
 * `code` and [links](https://…) (http(s) and in-app `/paths` only).
 */
import { Fragment, type ReactNode } from 'react';
import { Link } from 'react-router';

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const tok = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith('**')) {
      out.push(
        <strong key={key} className="font-semibold text-ink">
          {tok.slice(2, -2)}
        </strong>,
      );
    } else if (tok.startsWith('`')) {
      out.push(
        <code key={key} className="rounded-md border border-white/10 bg-white/[.06] px-1 py-px font-mono text-[0.86em] text-cyan-100">
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (tok.startsWith('[')) {
      const mm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
      const label = mm?.[1] ?? tok;
      const href = mm?.[2] ?? '';
      if (/^https?:\/\//i.test(href)) {
        out.push(
          <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline decoration-cyan-300/30 underline-offset-2 hover:decoration-cyan-300">
            {label}
          </a>,
        );
      } else if (href.startsWith('/')) {
        out.push(
          <Link key={key} to={href} className="text-cyan-300 underline decoration-cyan-300/30 underline-offset-2 hover:decoration-cyan-300">
            {label}
          </Link>,
        );
      } else {
        out.push(label);
      }
    } else {
      out.push(
        <em key={key} className="text-ink/90 italic">
          {tok.slice(1, -1)}
        </em>,
      );
    }
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: 'p'; lines: string[] }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'h'; text: string }
  | { kind: 'table'; rows: string[][] };

function cells(line: string): string[] {
  return line.replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
}

function parse(md: string): Block[] {
  const blocks: Block[] = [];
  let cur: Block | null = null;
  const flush = () => {
    if (cur) blocks.push(cur);
    cur = null;
  };
  for (const raw of md.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trim();
    if (!line) {
      flush();
      continue;
    }
    if (line.startsWith('|')) {
      if (/^\|?[\s:|-]+\|?$/.test(line) && line.includes('-')) continue; // header separator row
      const c = cur as Block | null;
      if (c && c.kind === 'table') c.rows.push(cells(line));
      else {
        flush();
        cur = { kind: 'table', rows: [cells(line)] };
      }
      continue;
    }
    const h = /^#{1,4}\s+(.*)$/.exec(line);
    const ul = /^[-*•]\s+(.*)$/.exec(line);
    const ol = /^\d+[.)]\s+(.*)$/.exec(line);
    if (h) {
      flush();
      blocks.push({ kind: 'h', text: h[1] });
    } else if (ul || ol) {
      const kind = ul ? 'ul' : 'ol';
      const text = (ul ?? ol)![1];
      const c = cur as Block | null;
      if (c && c.kind === kind) c.items.push(text);
      else {
        flush();
        cur = { kind, items: [text] };
      }
    } else {
      const c = cur as Block | null;
      if (c && c.kind === 'p') c.lines.push(line);
      else {
        flush();
        cur = { kind: 'p', lines: [line] };
      }
    }
  }
  flush();
  return blocks;
}

export function Markdownish({ source, className }: { source: string; className?: string }) {
  const blocks = parse(source);
  return (
    <div className={className}>
      {blocks.map((b, bi) => {
        const k = `b${bi}`;
        if (b.kind === 'h') {
          return (
            <div key={k} className="mt-3 font-display text-sm font-semibold text-ink first:mt-0">
              {inline(b.text, k)}
            </div>
          );
        }
        if (b.kind === 'table') {
          const [head, ...body] = b.rows;
          return (
            <div key={k} className="mt-2 overflow-x-auto rounded-xl border border-white/[.08] first:mt-0">
              <table className="w-full min-w-max border-collapse text-left text-[12.5px]">
                <thead>
                  <tr className="bg-white/[.04]">
                    {head.map((c, ci) => (
                      <th key={ci} className="px-3 py-2 text-[10.5px] font-medium uppercase tracking-[0.1em] text-muted">
                        {inline(c, `${k}-h${ci}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {body.map((r, ri) => (
                    <tr key={ri} className="border-t border-white/[.06]">
                      {r.map((c, ci) => (
                        <td key={ci} className="px-3 py-1.5 align-top text-ink/85">
                          {inline(c, `${k}-${ri}-${ci}`)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (b.kind === 'p') {
          return (
            <p key={k} className="mt-2 first:mt-0">
              {b.lines.map((l, li) => (
                <Fragment key={li}>
                  {li > 0 && <br />}
                  {inline(l, `${k}-${li}`)}
                </Fragment>
              ))}
            </p>
          );
        }
        const List = b.kind === 'ul' ? 'ul' : 'ol';
        return (
          <List key={k} className={`mt-2 space-y-1 pl-5 first:mt-0 ${b.kind === 'ul' ? 'list-disc marker:text-faint' : 'list-decimal marker:text-faint'}`}>
            {b.items.map((it, ii) => (
              <li key={ii}>{inline(it, `${k}-${ii}`)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
