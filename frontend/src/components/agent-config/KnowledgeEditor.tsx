// Knowledge-base section of the agent form: pasted text, system prompt, FAQ
// list and knowledge-file upload. Extracted from AgentConfigForm.tsx
// (verbatim JSX) — no behavior change.
"use client";

import { FaqItem } from "./types";

export interface KnowledgeEditorProps {
  knowledgeText: string; setKnowledgeText: (v: string) => void;
  systemPrompt: string; setSystemPrompt: (v: string) => void;
  faq: FaqItem[]; setFaq: (fn: (f: FaqItem[]) => FaqItem[]) => void;
  file: File | null; setFile: (f: File | null) => void;
  savedDocuments: { name: string }[];
  setSavedDocuments: (fn: (docs: { name: string }[]) => { name: string }[]) => void;
  hasText: boolean;
}

export function KnowledgeEditor(p: KnowledgeEditorProps) {
  return (
    <>
      <div>
        <label className="text-xs text-gray-400 font-medium">Knowledge base (pasted text / notes)</label>
        <textarea
          value={p.knowledgeText}
          disabled={!!p.file || p.savedDocuments.length > 0}
          onChange={(e) => p.setKnowledgeText(e.target.value)}
          rows={5}
          placeholder="Company facts, FAQs, product info..."
          className="input mt-1"
        />
      </div>
      <div>
        <label className="text-xs text-gray-400 font-medium">System prompt (optional)</label>
        <textarea
          value={p.systemPrompt}
          onChange={(e) => p.setSystemPrompt(e.target.value)}
          rows={3}
          placeholder="Extra instructions for the agent..."
          className="input mt-1"
        />
      </div>

      <div className="bg-gray-800/40 rounded-xl border border-gray-800 p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-gray-400 font-medium uppercase">FAQ (Q&A pairs)</span>
          <button onClick={() => p.setFaq((f) => [...f, { q: "", a: "" }])} className="text-xs text-blue-400">
            + Add
          </button>
        </div>
        {p.faq.length === 0 && <p className="text-[11px] text-gray-500">No FAQs yet. Add Q&A the agent should know.</p>}
        <div className="space-y-2">
          {p.faq.map((item, i) => (
            <div key={i} className="grid grid-cols-1 gap-1">
              <input
                value={item.q}
                onChange={(e) => p.setFaq((f) => f.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)))}
                placeholder="Question"
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
              />
              <div className="flex gap-1">
                <input
                  value={item.a}
                  onChange={(e) => p.setFaq((f) => f.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)))}
                  placeholder="Answer"
                  className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                />
                <button onClick={() => p.setFaq((f) => f.filter((_, j) => j !== i))} className="text-red-400 text-xs px-2">
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <label className="text-xs text-gray-400 font-medium">Upload knowledge file (.txt/.md/.csv/.json/.pdf)</label>
        {p.savedDocuments.length > 0 && (
          <div className="mb-2 rounded-lg border border-blue-500/30 bg-blue-500/10 p-2 text-xs">
            <div className="font-medium">Saved knowledge file</div>
            {p.savedDocuments.map((d, i) => (
              <div key={`${d.name}-${i}`} className="flex justify-between text-gray-300">
                <span>{d.name}</span>
                <button type="button" onClick={() => p.setSavedDocuments((docs) => docs.filter((_, j) => j !== i))} className="text-red-400">
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
        <input
          type="file"
          disabled={p.hasText}
          onChange={(e) => p.setFile(e.target.files?.[0] || null)}
          className="block w-full text-sm text-gray-400 mt-1 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-white"
        />
      </div>
    </>
  );
}
