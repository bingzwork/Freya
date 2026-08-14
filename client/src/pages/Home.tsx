// Style reminder: compose the reference as a calm, asymmetric command room.
// Keep the portrait atmospheric, actions tactile, and Signal Violet purposeful.
import { useState, type CSSProperties } from "react";
import {
  Bell,
  BrainCircuit,
  CheckSquare,
  ChevronDown,
  FileText,
  Grid3X3,
  Lightbulb,
  List,
  Menu,
  MessageSquare,
  Mic,
  Monitor,
  MoreHorizontal,
  Paperclip,
  Plus,
  Search,
  Send,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Waves,
  X,
} from "lucide-react";

const markUrl = "/manus-storage/freya-mark_83bbb001.png";
const heroUrl = "/manus-storage/freya-hero_040aeb69.png";

const conversationGroups = [
  {
    label: "Today",
    items: [
      "What is quantum computing?",
      "Build a Python web scraper",
      "Explain photosynthesis",
      "Plan a weekend trip",
    ],
  },
  {
    label: "Yesterday",
    items: ["How does a GPU work?", "Best practices for sleep", "Write a short story"],
  },
  { label: "This week", items: ["Freya memory system", "Workout routine"] },
];

const quickActions = [
  { label: "Brainstorm ideas", icon: Lightbulb, prompt: "Help me brainstorm ideas for " },
  { label: "Analyze a file", icon: FileText, prompt: "I want to analyze a file about " },
  { label: "Create a plan", icon: List, prompt: "Create a practical plan for " },
  { label: "More", icon: MoreHorizontal, prompt: "Show me more ways you can help with " },
];

function FreyaMark({ small = false }: { small?: boolean }) {
  return (
    <span className={small ? "freya-mark freya-mark--small" : "freya-mark"}>
      <img src={markUrl} alt="" />
    </span>
  );
}

function Sidebar({ onClose, onNewChat }: { onClose?: () => void; onNewChat: () => void }) {
  return (
    <aside className="sidebar" aria-label="Conversation history">
      <div className="sidebar-topline">
        <div className="brand-lockup">
          <FreyaMark small />
          <span>Freya</span>
        </div>
        {onClose && (
          <button className="icon-button sidebar-close" aria-label="Close menu" onClick={onClose}>
            <X size={18} />
          </button>
        )}
      </div>

      <button className="new-chat-button" onClick={onNewChat}>
        <Plus size={18} strokeWidth={2.2} />
        <span>New Chat</span>
      </button>

      <nav className="conversation-list">
        {conversationGroups.map((group) => (
          <div className="conversation-group" key={group.label}>
            <p className="group-label">{group.label}</p>
            {group.items.map((item, index) => (
              <button className={index === 0 && group.label === "Today" ? "conversation-item is-active" : "conversation-item"} key={item}>
                <MessageSquare size={15} strokeWidth={1.55} />
                <span>{item}</span>
                {index === 0 && group.label === "Today" && <MoreHorizontal size={16} className="conversation-more" />}
              </button>
            ))}
          </div>
        ))}
      </nav>

      <div className="profile-bar">
        <div className="avatar">F</div>
        <div className="profile-copy">
          <strong>Freya User</strong>
          <span>Personal workspace</span>
        </div>
        <ChevronDown size={15} className="profile-chevron" />
        <button className="icon-button settings-button" aria-label="Open settings">
          <Settings2 size={17} />
        </button>
      </div>
    </aside>
  );
}

function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  return (
    <header className="topbar">
      <button className="icon-button mobile-menu" aria-label="Open menu" onClick={onOpenMenu}>
        <Menu size={20} />
      </button>
      <button className="workspace-switcher" aria-label="Switch workspace">
        <span>Freya</span>
        <ChevronDown size={16} />
      </button>
      <div className="topbar-actions">
        <button className="icon-button" aria-label="Search">
          <Search size={20} />
        </button>
        <button className="icon-button grid-button" aria-label="Open apps">
          <Grid3X3 size={20} />
        </button>
        <button className="icon-button notification-button" aria-label="Notifications">
          <Bell size={20} />
          <span className="notification-dot" />
        </button>
        <button className="profile-orb" aria-label="Open account menu" />
      </div>
    </header>
  );
}

function Composer({
  value,
  setValue,
  onSend,
  notice,
}: {
  value: string;
  setValue: (value: string) => void;
  onSend: () => void;
  notice: string;
}) {
  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={(event) => { event.preventDefault(); onSend(); }}>
        <textarea
          aria-label="Message Freya"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="How can I help you today?"
          rows={2}
        />
        <div className="composer-toolbar">
          <div className="composer-tools">
            <button className="composer-tool icon-button" type="button" aria-label="Attach a file">
              <Paperclip size={18} />
            </button>
            <button className="tool-pill" type="button">
              <SlidersHorizontal size={15} />
              <span>Tools</span>
            </button>
          </div>
          <div className="composer-tools">
            <button className="composer-tool icon-button" type="button" aria-label="Use voice input">
              <Mic size={17} />
            </button>
            <button className="send-button" type="submit" aria-label="Send message">
              <Send size={18} />
            </button>
          </div>
        </div>
      </form>
      <p className={notice ? "composer-notice is-visible" : "composer-notice"} role="status">{notice || ""}</p>
    </div>
  );
}

function SystemsDock() {
  const systems = [
    { title: "Memory", subtitle: "Active", icon: BrainCircuit, color: "violet", dot: "green" },
    { title: "Learning", subtitle: "Observing", icon: Waves, color: "blue", dot: "violet" },
    { title: "Tasks", subtitle: "2 Running", icon: CheckSquare, color: "cobalt", dot: "blue" },
    { title: "System", subtitle: "Healthy", icon: Monitor, color: "indigo", dot: "green" },
  ];
  return (
    <section className="systems-dock" aria-label="Freya system status">
      {systems.map(({ title, subtitle, icon: Icon, color, dot }, index) => (
        <div className="system-item" key={title}>
          <div className={`system-icon system-icon--${color}`}><Icon size={21} strokeWidth={1.6} /></div>
          <div className="system-copy"><strong>{title}</strong><span>{subtitle} <i className={`status-dot status-dot--${dot}`} /></span></div>
          {index < systems.length - 1 && <span className="system-divider" />}
        </div>
      ))}
    </section>
  );
}

export default function Home() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");

  const startNewChat = () => {
    setMessage("");
    setNotice("New conversation ready");
    window.setTimeout(() => setNotice(""), 2400);
    setMenuOpen(false);
  };

  const sendMessage = () => {
    if (!message.trim()) {
      setNotice("Write a thought first, then send it my way.");
    } else {
      setNotice("Freya is listening…");
      setMessage("");
    }
    window.setTimeout(() => setNotice(""), 2600);
  };

  return (
    <main className="app-shell">
      {menuOpen && <button className="sidebar-scrim" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}
      <div className={menuOpen ? "sidebar-mobile is-open" : "sidebar-mobile"}>
        <Sidebar onClose={() => setMenuOpen(false)} onNewChat={startNewChat} />
      </div>
      <div className="desktop-sidebar"><Sidebar onNewChat={startNewChat} /></div>

      <section className="workspace" style={{ "--hero-art": `url(${heroUrl})` } as CSSProperties}>
        <div className="workspace-ambient" />
        <Topbar onOpenMenu={() => setMenuOpen(true)} />
        <div className="hero-art" aria-hidden="true" />

        <section className="welcome" aria-labelledby="greeting">
          <div className="welcome-mark"><FreyaMark /></div>
          <h1 id="greeting">Hi, I’m <span>Freya.</span></h1>
          <p>Your intelligent assistant. Always learning, always here.</p>
        </section>

        <div className="command-zone">
          <Composer value={message} setValue={setMessage} onSend={sendMessage} notice={notice} />
          <div className="quick-actions" aria-label="Suggested actions">
            {quickActions.map(({ label, icon: Icon, prompt }) => (
              <button className="quick-action" key={label} onClick={() => setMessage(prompt)}>
                <Icon size={16} strokeWidth={1.65} />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>

        <SystemsDock />
        <div className="workspace-footer"><Sparkles size={13} /> Freya adapts to the way you work</div>
      </section>
    </main>
  );
}
