import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createResponseTemplate,
  deleteResponseTemplate,
  listCategories,
  listResponseTemplates,
  updateResponseTemplate,
} from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import type { ResponseTemplate } from "../../api/types";

export function ResponseTemplatesPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<ResponseTemplate | "new" | null>(null);

  const templatesQuery = useQuery({
    queryKey: ["response-templates", "all"],
    queryFn: () => listResponseTemplates({ include_inactive: true }),
  });
  const categoriesQuery = useQuery({ queryKey: ["categories"], queryFn: listCategories });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => updateResponseTemplate(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["response-templates"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteResponseTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["response-templates"] }),
  });

  if (templatesQuery.isLoading) return <div className="view"><Loading /></div>;
  if (templatesQuery.isError) {
    return <div className="view"><ErrorBanner message={(templatesQuery.error as Error).message} /></div>;
  }

  const templates = templatesQuery.data ?? [];
  const categoriesById = new Map((categoriesQuery.data ?? []).map((c) => [c.id, c]));

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Шаблоны ответов
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          Добавить шаблон
        </button>
      </div>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Инженер вставляет шаблон одним кликом в карточке заявки. Шаблон без категории предлагается по любой заявке;
        с категорией — только по заявкам этой категории.
      </p>

      {templates.length === 0 && <EmptyState text="Шаблонов пока нет" />}
      {templates.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "1.4fr 2.4fr 1.2fr 150px" }}>
            <span>Название</span>
            <span>Текст</span>
            <span>Категория</span>
            <span></span>
          </div>
          {templates.map((t) => (
            <div className="list-row" style={{ gridTemplateColumns: "1.4fr 2.4fr 1.2fr 150px" }} key={t.id}>
              <span className="subject">
                {t.name}
                {!t.is_active && <span className="muted"> · выключен</span>}
              </span>
              <span className="muted">{t.body.length > 90 ? `${t.body.slice(0, 90)}…` : t.body}</span>
              <span className="muted">{t.category_id ? categoriesById.get(t.category_id)?.name ?? "—" : "Любая"}</span>
              <span style={{ display: "flex", gap: 10 }}>
                <button className="btn-link" onClick={() => setEditing(t)}>
                  Изменить
                </button>
                <button className="btn-link" onClick={() => toggleMutation.mutate({ id: t.id, is_active: !t.is_active })}>
                  {t.is_active ? "Выключить" : "Включить"}
                </button>
                <button className="btn-link" onClick={() => deleteMutation.mutate(t.id)}>
                  Удалить
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <TemplateModal
          template={editing === "new" ? null : editing}
          categories={categoriesQuery.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["response-templates"] });
          }}
        />
      )}
    </div>
  );
}

function TemplateModal({
  template,
  categories,
  onClose,
  onSaved,
}: {
  template: ResponseTemplate | null;
  categories: { id: number; name: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(template?.name ?? "");
  const [body, setBody] = useState(template?.body ?? "");
  const [categoryId, setCategoryId] = useState<number | "">(template?.category_id ?? "");
  const [error, setError] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = { name: name.trim(), body: body.trim(), category_id: categoryId || null };
      return template ? updateResponseTemplate(template.id, payload) : createResponseTemplate(payload);
    },
    onSuccess: onSaved,
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось сохранить шаблон"),
  });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{template ? "Шаблон ответа" : "Новый шаблон"}</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}
          <div className="form-row">
            <label className="form-label">Название (видно только сотрудникам)</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Запрос доступа к 1С" />
          </div>
          <div className="form-row">
            <label className="form-label">Категория</label>
            <select value={categoryId} onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Любая категория</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label">Текст ответа</label>
            <textarea rows={7} value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn btn-primary"
            disabled={!name.trim() || !body.trim() || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            Сохранить
          </button>
        </div>
      </div>
    </div>
  );
}
