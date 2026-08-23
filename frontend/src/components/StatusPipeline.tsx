import type { TicketStatus } from "../api/types";
import { STATUS_LABELS, STATUS_TRANSITIONS } from "../lib/labels";

/** Основной путь заявки. Ожидания и отмена сюда не входят: это не этапы, а
 *  отклонения от пути, и в одну линию с ним они не выстраиваются. */
const MAIN_PATH: TicketStatus[] = ["new", "assigned", "in_progress", "resolved", "closed"];

/** Ответвления — состояния, из которых заявка возвращается на основной путь
 *  или уходит с него насовсем. */
const BRANCHES: TicketStatus[] = ["waiting_customer", "waiting_third_party", "cancelled"];

const HINTS: Partial<Record<TicketStatus, string>> = {
  waiting_customer: "таймер решения на паузе",
  waiting_third_party: "таймер решения на паузе",
  cancelled: "не работа: дубль, ошиблись адресом",
  resolved: "закроется сама через несколько дней",
};

/** Путь заявки в виде дорожки вместо списка кнопок «→ Статус».
 *
 *  Раньше показывались только доступные переходы, и по ним невозможно было
 *  понять ни где заявка находится в общем процессе, ни что будет дальше:
 *  «→ В работе», «→ Отменена» выглядели равнозначными вариантами, хотя один
 *  ведёт вперёд, а другой закрывает заявку насовсем.
 */
export function StatusPipeline({
  status,
  disabled,
  onChange,
}: {
  status: TicketStatus;
  disabled?: boolean;
  onChange: (next: TicketStatus) => void;
}) {
  const allowed = STATUS_TRANSITIONS[status] ?? [];
  const currentIndex = MAIN_PATH.indexOf(status);
  // Заявка в ожидании физически находится между «В работе» и «Решена»:
  // подсвечиваем этот участок, чтобы дорожка не выглядела пустой.
  const effectiveIndex = currentIndex >= 0 ? currentIndex : MAIN_PATH.indexOf("in_progress");

  return (
    <div className="pipeline">
      <div className="pipeline-track">
        {MAIN_PATH.map((step, index) => {
          const isCurrent = step === status;
          const isDone = index < effectiveIndex;
          const isNext = allowed.includes(step);
          const state = isCurrent ? "current" : isDone ? "done" : isNext ? "next" : "future";
          return (
            <button
              key={step}
              type="button"
              className={`pipeline-step ${state}`}
              disabled={disabled || !isNext}
              title={
                isCurrent
                  ? "Текущий статус"
                  : isNext
                    ? `Перевести в «${STATUS_LABELS[step]}»`
                    : isDone
                      ? "Этап пройден"
                      : "Недоступно из текущего статуса"
              }
              onClick={() => isNext && onChange(step)}
            >
              <span className="pipeline-dot" />
              <span className="pipeline-label">{STATUS_LABELS[step]}</span>
              {HINTS[step] && isNext && <span className="pipeline-hint">{HINTS[step]}</span>}
            </button>
          );
        })}
      </div>

      {(status === "waiting_customer" || status === "waiting_third_party") && (
        <p className="pipeline-paused">
          {STATUS_LABELS[status]} — таймер решения на паузе. Вернуть в работу можно кнопкой ниже.
        </p>
      )}

      <div className="pipeline-branches">
        {BRANCHES.filter((step) => allowed.includes(step)).map((step) => (
          <button
            key={step}
            type="button"
            className="btn btn-ghost"
            disabled={disabled}
            title={HINTS[step]}
            onClick={() => {
              if (step !== "cancelled" || window.confirm("Отменить заявку? Это не «решена» — работа по ней не велась.")) {
                onChange(step);
              }
            }}
          >
            {STATUS_LABELS[step]}
          </button>
        ))}
        {BRANCHES.includes(status) && <span className="muted">Сейчас: {STATUS_LABELS[status]}</span>}
      </div>
    </div>
  );
}
