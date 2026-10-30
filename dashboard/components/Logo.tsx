// A coin with a mint leaf. Drawn for this project; no third-party mark.
export default function Logo() {
  return (
    <svg className="logo" viewBox="0 0 48 48" width="48" height="48" aria-hidden>
      <circle cx="24" cy="24" r="22" fill="var(--primary)" />
      <circle cx="24" cy="24" r="17" fill="none" stroke="#fff" strokeOpacity="0.35" strokeWidth="1.5" />
      <path d="M15 31c0-9 6.5-15 18-16-0.5 11.5-6.5 18-15.5 18" fill="#fff" />
      <path d="M17 31.5c3.5-4 7-7.5 11.5-11" stroke="var(--primary)" strokeWidth="1.8" strokeLinecap="round" fill="none" />
    </svg>
  );
}
