import { useState } from "react";
import { BrandMark } from "../components/BrandMark";
import { IconCheck, IconEye, IconEyeOff } from "../components/icons";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner } from "../components/ui";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const requested = location.state?.from;
  const destination = typeof requested === "string" && requested.startsWith("/") && !requested.startsWith("//") && requested !== "/login" ? requested : "/dashboard";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to={destination} replace />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      navigate(destination, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-intro"><span className="login-kicker"><span className="login-kicker-dot"/> ЕДИНОЕ ПРОСТРАНСТВО ПОДДЕРЖКИ</span><h2>Каждое обращение<br />под <span>контролем.</span></h2><p>От первого сообщения до принятого результата.<br />Команда, клиенты и планы работают вместе.</p><div className="login-features"><span><IconCheck size={15}/> Заявки и SLA</span><span><IconCheck size={15}/> Проекты и согласования</span><span><IconCheck size={15}/> Личный кабинет клиента</span></div><div className="login-intro-line" /></div>
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-brand">
          <BrandMark />
          <div>
            <h1>Открытые Горизонты</h1>
            <p className="muted">Служба поддержки</p>
          </div>
        </div>

        <div className="login-heading"><h2>Вход в рабочее пространство</h2><p className="muted">Используйте учётную запись сотрудника.</p></div>
        {error && <ErrorBanner message={error} />}

        <div className="form-row">
          <label className="form-label" htmlFor="login-email">Электронная почта</label>
          <input
            id="login-email"
            placeholder="name@company.ru"
            autoFocus
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="form-row">
          <label className="form-label" htmlFor="login-password">Пароль</label>
          <div className="password-control"><input
            id="login-password"
            placeholder="Введите пароль"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          /><button type="button" className="password-toggle" aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? <IconEyeOff size={18}/> : <IconEye size={18}/>}</button></div>
        </div>

        <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
          {submitting ? "Входим…" : "Войти"}
        </button>
        <p className="login-footer">Клиентам — <a href="/portal">личный кабинет поддержки →</a></p>
      </form>
    </div>
  );
}
