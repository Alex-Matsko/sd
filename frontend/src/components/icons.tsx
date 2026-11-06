import type { ReactNode } from "react";

interface IconProps {
  size?: number;
  className?: string;
}

function base(paths: ReactNode, { size = 18, className }: IconProps = {}) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {paths}
    </svg>
  );
}

export const IconInbox = (p: IconProps) =>
  base(
    <>
      <path d="M3 12h4l2 3h6l2-3h4" />
      <path d="M5 5h14l2 7v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-7z" />
    </>,
    p
  );

export const IconTicket = (p: IconProps) =>
  base(
    <>
      <path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4z" />
      <path d="M10 6v12" strokeDasharray="2 2" />
    </>,
    p
  );

export const IconPlus = (p: IconProps) => base(<path d="M12 5v14M5 12h14" />, p);

export const IconBuilding = (p: IconProps) =>
  base(
    <>
      <rect x="4" y="3" width="16" height="18" rx="1" />
      <path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M10 21v-4h4v4" />
    </>,
    p
  );

export const IconUsers = (p: IconProps) =>
  base(
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
      <circle cx="17" cy="9" r="2.4" />
      <path d="M15.5 14.2c2.4.4 4.5 2.6 4.5 5.8" />
    </>,
    p
  );

export const IconFileText = (p: IconProps) =>
  base(
    <>
      <path d="M7 3h7l4 4v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
      <path d="M14 3v4h4M9 12h6M9 16h6M9 8h2" />
    </>,
    p
  );

export const IconServer = (p: IconProps) =>
  base(
    <>
      <rect x="3" y="4" width="18" height="6" rx="1" />
      <rect x="3" y="14" width="18" height="6" rx="1" />
      <path d="M7 7h.01M7 17h.01" />
    </>,
    p
  );

export const IconPhone = (p: IconProps) =>
  base(
    <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .3 1.9.6 2.8a2 2 0 0 1-.4 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.5 2.8.6a2 2 0 0 1 1.8 2z" />,
    p
  );

export const IconSettings = (p: IconProps) =>
  base(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </>,
    p
  );

export const IconGrid = (p: IconProps) =>
  base(
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>,
    p
  );

export const IconRoute = (p: IconProps) =>
  base(
    <>
      <circle cx="6" cy="6" r="2.2" />
      <circle cx="18" cy="18" r="2.2" />
      <path d="M8 6h8a4 4 0 0 1 4 4v0a4 4 0 0 1-4 4H8" />
    </>,
    p
  );

export const IconChevronDown = (p: IconProps) => base(<path d="M6 9l6 6 6-6" />, p);

export const IconChevronRight = (p: IconProps) => base(<path d="M9 6l6 6-6 6" />, p);

export const IconClock = (p: IconProps) =>
  base(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>,
    p
  );

export const IconLogout = (p: IconProps) =>
  base(
    <>
      <path d="M9 21H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h4" />
      <path d="M16 17l5-5-5-5M21 12H9" />
    </>,
    p
  );

export const IconSearch = (p: IconProps) =>
  base(
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.35-4.35" />
    </>,
    p
  );

export const IconAlertTriangle = (p: IconProps) =>
  base(
    <>
      <path d="M10.3 3.9 1.8 18a1 1 0 0 0 .9 1.5h18.6a1 1 0 0 0 .9-1.5L13.7 3.9a1 1 0 0 0-1.4 0z" />
      <path d="M12 9v4M12 16.5h.01" />
    </>,
    p
  );

export const IconCheck = (p: IconProps) => base(<path d="M4 12l5 5L20 6" />, p);

export const IconPaperclip = (p: IconProps) =>
  base(<path d="M21 11.5 12.4 20a4.7 4.7 0 0 1-6.6-6.6L14.6 4.6a3.1 3.1 0 0 1 4.4 4.4l-9 8.9a1.5 1.5 0 0 1-2.1-2.1l7.9-7.9" />, p);

export const IconBell = (p: IconProps) =>
  base(
    <>
      <path d="M6 9a6 6 0 0 1 12 0c0 4 1.5 5.5 2 6H4c.5-.5 2-2 2-6Z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </>,
    p
  );

export const IconProjects = (p: IconProps) => base(<><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16M15 4v16M5.5 8h1M11.5 8h1M17.5 8h1M5.5 12h1M11.5 12h1"/></>, p);
export const IconMenu = (p: IconProps) => base(<path d="M4 6h16M4 12h16M4 18h16"/>, p);
export const IconEye = (p: IconProps) => base(<><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></>, p);
export const IconEyeOff = (p: IconProps) => base(<><path d="m3 3 18 18M10.6 5.1C11 5 11.5 5 12 5c6.5 0 10 7 10 7a20 20 0 0 1-3 3.8M6.2 6.2A22 22 0 0 0 2 12s3.5 7 10 7a12 12 0 0 0 5.8-1.7M9.9 9.9a3 3 0 0 0 4.2 4.2"/></>, p);
export const IconArrowRight = (p: IconProps) => base(<path d="M4 12h16m-6-6 6 6-6 6"/>, p);
