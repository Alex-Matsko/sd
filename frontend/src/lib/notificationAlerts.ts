/** Звук и мигание вкладки при новом уведомлении.
 *
 *  Колокольчик виден, только когда инженер смотрит на панель. Заявка при
 *  этом приходит, пока он в другой вкладке или в другом окне — и о ней
 *  узнают, вернувшись. Поэтому здесь два сигнала, работающих именно в
 *  фоновой вкладке: короткий звук и мигающий заголовок.
 */

const SOUND_PREF_KEY = "sd_notification_sound";
const FLASH_INTERVAL_MS = 1200;

export function isSoundEnabled(): boolean {
  try {
    // По умолчанию звук включён: инженер, пропустивший аварию, — дороже
    // одного лишнего сигнала. Выключается кнопкой в колокольчике.
    return localStorage.getItem(SOUND_PREF_KEY) !== "off";
  } catch {
    // Приватный режим и заблокированные хранилища: звук просто остаётся
    // включённым, падать из-за настройки нельзя.
    return true;
  }
}

export function setSoundEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(SOUND_PREF_KEY, enabled ? "on" : "off");
  } catch {
    /* настройка не сохранится — не повод ломать интерфейс */
  }
}

let audioContext: AudioContext | null = null;

/** Синтезирует короткий сигнал вместо проигрывания файла.
 *
 *  Файл пришлось бы класть в бандл и разрешать в CSP; здесь достаточно двух
 *  тонов. Громкость намеренно низкая: это подсказка, а не сирена.
 */
export function playNotificationSound(): void {
  if (!isSoundEnabled()) return;
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    audioContext = audioContext ?? new Ctor();
    // Браузер держит контекст приостановленным, пока страница не получила
    // жеста пользователя. Вход в систему — такой жест, но после
    // восстановления вкладки контекст может снова уснуть.
    if (audioContext.state === "suspended") void audioContext.resume();

    const now = audioContext.currentTime;
    [880, 1174.7].forEach((frequency, index) => {
      const oscillator = audioContext!.createOscillator();
      const gain = audioContext!.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = frequency;
      const start = now + index * 0.12;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.09, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.18);
      oscillator.connect(gain).connect(audioContext!.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.2);
    });
  } catch {
    // Звук — вспомогательный сигнал. Если браузер его не даёт, уведомление
    // всё равно уже в колокольчике.
  }
}

let flashTimer: number | null = null;
let originalTitle: string | null = null;

/** Мигание заголовка вкладки, пока есть непрочитанные и вкладка не активна. */
export function startTitleFlash(unreadCount: number): void {
  if (originalTitle === null) originalTitle = document.title;
  stopTimerOnly();

  const alert = `(${unreadCount}) Новое уведомление`;
  let showAlert = true;
  document.title = alert;
  flashTimer = window.setInterval(() => {
    document.title = showAlert ? originalTitle! : alert;
    showAlert = !showAlert;
  }, FLASH_INTERVAL_MS);
}

export function stopTitleFlash(): void {
  stopTimerOnly();
  if (originalTitle !== null) {
    document.title = originalTitle;
    originalTitle = null;
  }
}

function stopTimerOnly(): void {
  if (flashTimer !== null) {
    window.clearInterval(flashTimer);
    flashTimer = null;
  }
}
