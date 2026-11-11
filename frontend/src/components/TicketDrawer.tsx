import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { TicketDetailPage } from "../pages/TicketDetailPage";

export function TicketDrawer() {
  const dialog = useRef<HTMLDialogElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const queueReturn = location.state?.queueReturn ?? "/tickets";
  useEffect(() => {
    const node = dialog.current; node?.showModal();
    return () => { node?.close(); };
  }, []);
  return <dialog ref={dialog} className="ticket-drawer" aria-label="Карточка заявки" onCancel={(e) => { if (e.target !== e.currentTarget) return; e.preventDefault(); navigate(-1); }} onClick={(e) => { if (e.target === e.currentTarget) navigate(-1); }}>
    <div className="ticket-drawer-frame"><header className="ticket-drawer-header"><span>Карточка заявки</span><div>
      <Link to={location.pathname} replace state={{ queueReturn }}>Открыть на странице ↗</Link>
      <button type="button" aria-label="Закрыть карточку заявки" onClick={() => navigate(-1)}>×</button>
    </div></header><div className="ticket-drawer-body"><TicketDetailPage embedded /></div></div>
  </dialog>;
}
