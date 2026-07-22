import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createCategory, deleteCategory, listCategories } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { IconPlus } from "../../components/icons";

export function CategoriesPage() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState<number | "">("");
  const categoriesQuery = useQuery({ queryKey: ["categories"], queryFn: listCategories });

  const createMutation = useMutation({
    mutationFn: () => createCategory({ name: name.trim(), parent_id: parentId ? Number(parentId) : null }),
    onSuccess: () => {
      setName("");
      setParentId("");
      qc.invalidateQueries({ queryKey: ["categories"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteCategory(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["categories"] }),
  });

  if (categoriesQuery.isLoading) return <div className="view"><Loading /></div>;
  if (categoriesQuery.isError) return <div className="view"><ErrorBanner message={(categoriesQuery.error as Error).message} /></div>;

  const categories = categoriesQuery.data ?? [];
  const topLevel = categories.filter((c) => c.parent_id === null);
  const childrenOf = (id: number) => categories.filter((c) => c.parent_id === id);

  return (
    <div className="view">
      <h1 className="view-title">Категории</h1>

      <div className="panel form-panel">
        <div className="panel-head">
          <h2>Новая категория</h2>
        </div>
        {createMutation.isError && <ErrorBanner message={(createMutation.error as Error).message} />}
        <div className="form-row-inline">
          <input type="text" placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} />
          <select value={parentId} onChange={(e) => setParentId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Без родителя (верхний уровень)</option>
            {topLevel.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" disabled={!name.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>
            <IconPlus size={15} /> Добавить
          </button>
        </div>
      </div>

      {topLevel.length === 0 && <EmptyState text="Категорий пока нет" />}
      {topLevel.map((cat) => (
        <div className="panel" key={cat.id}>
          <div className="panel-head">
            <h2>{cat.name}</h2>
            <button className="btn btn-ghost btn-danger" onClick={() => deleteMutation.mutate(cat.id)}>
              Удалить
            </button>
          </div>
          <div className="tag-row">
            {childrenOf(cat.id).map((child) => (
              <span className="channel-tag" key={child.id}>
                {child.name}
                <button className="icon-btn icon-btn-inline" onClick={() => deleteMutation.mutate(child.id)}>
                  ×
                </button>
              </span>
            ))}
            {childrenOf(cat.id).length === 0 && <span className="muted">Подкатегорий нет</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
