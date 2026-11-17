import { useParams } from "react-router-dom";
import { ReleaseWorkbench } from "./workbench";

export function Component() {
  const { projectId = "" } = useParams();
  return <ReleaseWorkbench key={projectId} project={projectId} />;
}
