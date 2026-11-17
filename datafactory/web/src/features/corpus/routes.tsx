import { useParams } from "react-router-dom";
import { SnapshotDetail } from "./snapshot-detail";

export function Component() {
  const { projectId = "", snapshotId = "" } = useParams();
  return (
    <SnapshotDetail
      key={`${projectId}:${snapshotId}`}
      projectId={projectId}
      snapshotId={snapshotId}
    />
  );
}
