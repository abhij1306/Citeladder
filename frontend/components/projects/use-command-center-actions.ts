import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';

import { opportunitiesApi } from '@/lib/api/opportunities';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import type { CommandCenter, Opportunity, Project } from '@/lib/api/types';

export function useCommandCenterActions(data: CommandCenter, project: Project) {
  const queryClient = useQueryClient();
  const [downloadError, setDownloadError] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [actions, setActions] = useState(data.actions);
  const [reorderError, setReorderError] = useState(false);
  const orderVersion = useRef(data.action_order_version);
  const reorderPending = useRef(false);
  const reorder = useMutation({
    mutationFn: (ordered: Opportunity[]) =>
      opportunitiesApi.updateOrder(project.id, {
        ordered_opportunity_ids: ordered.map((row) => row.id),
        expected_version: orderVersion.current,
      }),
    onSuccess: (result) => {
      orderVersion.current = result.version;
      reorderPending.current = false;
      setReorderError(false);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projects.commandCenter(project.id),
      });
    },
    onError: () => {
      reorderPending.current = false;
      orderVersion.current = data.action_order_version;
      setActions(data.actions);
      setReorderError(true);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projects.commandCenter(project.id),
      });
    },
  });
  return {
    actions,
    downloadError,
    downloading,
    reorderError,
    reorderPending: reorder.isPending,
    move: (from: number, to: number) =>
      moveActions(from, to, actions, reorderPending, setActions, setReorderError, reorder),
    download: () => downloadReport(project, setDownloading, setDownloadError),
  };
}

function moveActions(
  from: number,
  to: number,
  actions: Opportunity[],
  pending: React.MutableRefObject<boolean>,
  setActions: (actions: Opportunity[]) => void,
  setError: (value: boolean) => void,
  reorder: { mutate: (actions: Opportunity[]) => void },
) {
  if (
    pending.current ||
    from < 0 ||
    to < 0 ||
    from >= actions.length ||
    to >= actions.length ||
    from === to
  )
    return;
  const next = [...actions];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  setActions(next);
  setError(false);
  pending.current = true;
  reorder.mutate(next);
}

async function downloadReport(
  project: Project,
  setDownloading: (value: boolean) => void,
  setError: (value: boolean) => void,
) {
  setDownloading(true);
  setError(false);
  try {
    const blob = await projectsApi.downloadExecutiveReport(project.id);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `citeladder-${project.brand_name || project.name}-report.pdf`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  } catch {
    setError(true);
  } finally {
    setDownloading(false);
  }
}
