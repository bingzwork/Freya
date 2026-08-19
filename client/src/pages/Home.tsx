import { useEffect, useRef, useState } from "react";
import { Menu, Mic, Paperclip, Plus, Send, SlidersHorizontal, X } from "lucide-react";
import AvatarPanel from "../avatar/AvatarPanel";

const API_BASE = "";
const api = (path: string) => API_BASE + path;
const ACCEPT = [".jpg", ".jpeg", ".png", ".webp", ".mp3", ".wav", ".m4a", ".flac", ".mp4", ".mov", ".webm", ".txt", ".md", ".pdf", ".docx", ".csv", ".xlsx", ".json"].join(",");
const SUPPORTED = new Set(ACCEPT.split(","));

type ImageResult = {
  title: string;
  image_url: string;
  thumbnail_url: string;
  url: string;
  source_domain: string;
  snippet: string;
  match_type?: string;
  relevance?: string;
};
type Message = { id: string; role: "user" | "assistant"; text: string; attachments?: { name: string; type: string; size: number }[]; imageResults?: ImageResult[] };
type Capability = { name: string; available: boolean };

function safeHttpUrl(value: unknown): string {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw, window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
  } catch {
    return "";
  }
}

function normalizeImageResults(value: unknown): ImageResult[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const output: ImageResult[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const imageUrl = safeHttpUrl(record.image_url || record.imageUrl || record.thumbnail_url || record.thumbnail);
    if (!imageUrl || seen.has(imageUrl)) continue;
    seen.add(imageUrl);
    output.push({
      title: String(record.title || record.name || "Image result"),
      image_url: imageUrl,
      thumbnail_url: safeHttpUrl(record.thumbnail_url || record.thumbnail) || imageUrl,
      url: safeHttpUrl(record.url || record.source_url),
      source_domain: String(record.source_domain || record.domain || ""),
      snippet: String(record.snippet || ""),
      match_type: String(record.match_type || record.matchType || ""),
      relevance: String(record.relevance || ""),
    });
    if (output.length >= 12) break;
  }
  return output;
}

function formatBytes(value: number): string { if (!value) return "0 B"; const units = ["B", "KB", "MB", "GB"]; const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024))); return `${(value / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`; }
function fileKind(file: File): string { const suffix = "." + (file.name.split(".").pop() || "").toLowerCase(); if (file.type.startsWith("image/") || [".jpg", ".jpeg", ".png", ".webp"].includes(suffix)) return "image"; if (file.type.startsWith("audio/") || [".mp3", ".wav", ".m4a", ".flac"].includes(suffix)) return "audio"; if (file.type.startsWith("video/") || [".mp4", ".mov", ".webm"].includes(suffix)) return "video"; return "document"; }

function Sidebar({ onNewChat, onClose }: { onNewChat: () => void; onClose?: () => void }) { return <aside className="sidebar" aria-label="Conversation sidebar"><div className="sidebar-brand"><span className="freya-mark" aria-hidden="true">F</span><span>Freya</span></div><button className="new-chat-button" type="button" onClick={() => { onNewChat(); onClose?.(); }}><Plus size={16} /> New Chat</button><div className="conversation-history" aria-label="Conversation history"><span className="history-caption">Local workspace</span><span className="history-item">Current conversation</span></div><div className="sidebar-footnote">Private local session</div></aside>; }
function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) { return <header className="topbar"><button className="icon-button mobile-menu" type="button" aria-label="Open menu" onClick={onOpenMenu}><Menu size={20} /></button><div className="topbar-title">Freya workspace</div><span className="topbar-status"><i /> local</span></header>; }

function Composer({ value, setValue, onSend, setNotice }: { value: string; setValue: (value: string) => void; onSend: (files: File[]) => Promise<void>; setNotice: (value: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null); const [files, setFiles] = useState<File[]>([]); const [listening, setListening] = useState(false); const [toolsOpen, setToolsOpen] = useState(false); const [capabilities, setCapabilities] = useState<Capability[]>([]); const [dragging, setDragging] = useState(false); const previews = useRef(new Map<string, string>());
  const voiceSupported = typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);
  const addFiles = (picked: File[]) => { const accepted = picked.filter((file) => SUPPORTED.has("." + (file.name.split(".").pop() || "").toLowerCase())); if (accepted.length !== picked.length) setNotice("Some files were skipped because their type is not supported."); setFiles((current) => [...current, ...accepted].slice(0, 8)); };
  useEffect(() => () => { previews.current.forEach((url) => URL.revokeObjectURL(url)); }, []);
  const loadTools = async () => { if (toolsOpen) { setToolsOpen(false); return; } try { const response = await fetch(api("/api/capabilities")); const data = await response.json(); setCapabilities(Array.isArray(data.capabilities) ? data.capabilities : []); } catch { setCapabilities([]); } setToolsOpen(true); };
  const startListening = () => { if (!voiceSupported) { setNotice("Microphone speech recognition is unavailable in this browser."); return; } const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition; const recognition = new Recognition(); recognition.lang = "en-US"; recognition.interimResults = false; recognition.continuous = false; recognition.onstart = () => { setListening(true); setNotice("Listening…"); }; recognition.onresult = (event: any) => { const transcript = String(event.results?.[0]?.[0]?.transcript || "").trim(); if (transcript) setValue(`${value}${value ? " " : ""}${transcript}`); }; recognition.onerror = () => { setListening(false); setNotice("Microphone input could not be read."); }; recognition.onend = () => { setListening(false); setNotice(""); }; recognition.start(); };
  return <form className={`composer ${dragging ? "composer--dragging" : ""}`} onSubmit={async (event) => { event.preventDefault(); const selected = files; setFiles([]); await onSend(selected); }} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(Array.from(event.dataTransfer.files)); }} onPaste={(event) => { const pasted = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/")); if (pasted.length) { event.preventDefault(); addFiles(pasted); } }}>
    <input ref={fileRef} type="file" hidden multiple accept={ACCEPT} onChange={(event) => { addFiles(Array.from(event.target.files || [])); event.currentTarget.value = ""; }} />
    {files.length > 0 && <div className="file-chips" aria-label="Selected files">{files.map((file, index) => { const kind = fileKind(file); const key = `${file.name}-${index}`; let preview = previews.current.get(key); if (!preview && kind === "image") { preview = URL.createObjectURL(file); previews.current.set(key, preview); } return <span className="file-chip" key={key}>{preview ? <img src={preview} alt="" /> : <span className={`file-chip-icon file-chip-icon--${kind}`}>{kind.slice(0, 1).toUpperCase()}</span>}<span className="file-chip-copy"><strong>{file.name}</strong><small>{kind} · {formatBytes(file.size)}</small></span><button type="button" aria-label={`Remove ${file.name}`} onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}><X size={13} /></button></span>; })}</div>}
    <div className="composer-row"><button className="composer-tool icon-button" type="button" aria-label="Attach files" title="Attach files" onClick={() => fileRef.current?.click()}><Paperclip size={18} /></button><textarea value={value} onChange={(event) => setValue(event.target.value)} placeholder={dragging ? "Drop files here…" : "Message Freya…"} aria-label="Message Freya" rows={1} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><button className={`composer-tool icon-button ${listening ? "is-listening" : ""}`} type="button" aria-label="Use microphone" title={listening ? "Listening" : "Use microphone"} onClick={startListening}><Mic size={18} /></button><button className="send-button" type="submit" aria-label="Send message" title="Send message"><Send size={17} /></button></div>
    <div className="composer-meta"><button className="tools-toggle" type="button" onClick={loadTools}><SlidersHorizontal size={14} /> {toolsOpen ? "Hide capabilities" : "Capabilities"}</button><span>Enter to send · Shift+Enter for a new line</span></div>{toolsOpen && <div className="tools-popover">{capabilities.length === 0 ? <span className="tools-empty">No capability list available.</span> : capabilities.map((capability) => <span key={capability.name} className="capability-pill">{capability.name}</span>)}</div>}
  </form>;
}

const UI_REQUEST_TIMEOUT_MS = 180000;

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit, timeoutMs = UI_REQUEST_TIMEOUT_MS) {

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try { return await fetch(input, { ...init, signal: controller.signal }); }
  finally { window.clearTimeout(timeout); }
}

function Home() { const [menuOpen, setMenuOpen] = useState(false); const [message, setMessage] = useState(""); const [messages, setMessages] = useState<Message[]>([]); const [notice, setNotice] = useState(""); const [sending, setSending] = useState(false);
  const sendMessage = async (files: File[]) => { if (sending) return; if (!message.trim() && files.length === 0) { setNotice("Write a message or attach a file first."); return; } const text = message.trim(); setMessage(""); setSending(true); const attachmentRecords = files.map((file) => ({ name: file.name, type: fileKind(file), size: file.size })); setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", text, attachments: attachmentRecords }]); try { const paths: string[] = []; for (const file of files) { setNotice(`Uploading ${file.name}…`); const response = await fetchWithTimeout(api(`/api/upload?filename=${encodeURIComponent(file.name)}`), { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file }); const data = await response.json(); if (!response.ok) throw new Error(data.error || `Could not upload ${file.name}`); paths.push(data.path); } setNotice(files.length ? "Reading attachments…" : "Thinking…"); const response = await fetchWithTimeout(api("/api/chat"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, attachments: paths }) }); const data = await response.json(); if (!response.ok) throw new Error(data.error || "Freya could not complete the request."); setMessages((current) => [...current, { id: crypto.randomUUID(), role: "assistant", text: String(data.answer || ""), imageResults: normalizeImageResults(data.image_results) }]); setNotice(""); } catch (error) { setNotice(error instanceof DOMException && error.name === "AbortError" ? "Freya timed out before completing the request." : error instanceof Error ? error.message : "Freya could not complete the request."); } finally { setSending(false); } };
  const newChat = () => { setMessages([]); setMessage(""); setNotice(""); }; useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, []);
  return <div className="app-shell"><aside className={`desktop-sidebar ${menuOpen ? "is-open" : ""}`}><Sidebar onNewChat={newChat} onClose={() => setMenuOpen(false)} /></aside>{menuOpen && <button className="mobile-scrim" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}<main className="workspace"><Topbar onOpenMenu={() => setMenuOpen(true)} /><div className="workspace-body"><section className="chat-column"><div className={`conversation-view ${messages.length ? "has-messages" : ""}`}>{messages.length === 0 ? <div className="welcome"><span className="freya-hero-mark">F</span><p className="eyebrow">Local intelligence workspace</p><h1>What can I help you make sense of?</h1><p className="welcome-copy">Attach an image, recording, video, or document. Freya keeps the work in this local session and routes it through the capabilities that fit your request.</p></div> : messages.map((item) => <article className={`message message--${item.role}`} key={item.id}>{item.role === "assistant" && <div className="message-role">Freya</div>}{item.attachments?.length ? <div className="message-attachments">{item.attachments.map((attachment) => <span key={`${attachment.name}-${attachment.size}`} className="message-attachment"><span>{attachment.type}</span><strong>{attachment.name}</strong><small>{formatBytes(attachment.size)}</small></span>)}</div> : null}<div className="message-text">{item.text || "Attached files"}</div>{item.imageResults?.length ? <div className="image-results" aria-label="Image research results">{item.imageResults.map((result, index) => <article className="image-result-card" key={`${result.image_url}-${index}`}><img src={result.thumbnail_url} alt={result.title} loading="lazy" onError={(event) => { event.currentTarget.style.display = "none"; }} /><div className="image-result-copy"><strong>{result.title}</strong>{result.source_domain && <small>{result.source_domain}</small>}{(result.match_type || result.relevance) && <small>{[result.match_type, result.relevance].filter(Boolean).join(" · ")}</small>}{result.snippet && <p>{result.snippet}</p>}<div className="image-result-links">{result.url && <a href={result.url} target="_blank" rel="noreferrer">View source</a>}{result.image_url && <a href={result.image_url} target="_blank" rel="noreferrer">Open image</a>}</div></div></article>)}</div> : null}</article>)}</div><Composer value={message} setValue={setMessage} onSend={sendMessage} setNotice={setNotice} />{notice && <p className="composer-notice" role="status">{notice}</p>}</section><section className="avatar-column"><AvatarPanel /></section></div></main></div>; }
export default Home;

