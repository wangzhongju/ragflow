import { BackendVariant } from '@/utils/backend-variant';
import Workbench from './workbench';
export default function DataFactory() {
  return (
    <BackendVariant
      python={<Workbench />}
      go={<div className="p-8">数据制作需要连接 Python 后端。</div>}
    />
  );
}
