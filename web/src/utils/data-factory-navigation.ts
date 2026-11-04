import { pickByBackend } from './backend-variant';
export const supportsDataFactory = () =>
  pickByBackend({ python: true, go: false });
