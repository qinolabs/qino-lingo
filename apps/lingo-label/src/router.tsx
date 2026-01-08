import { createRouter } from "@tanstack/react-router";

import { DefaultCatchBoundary } from "@qino-lingo/ui/components/default-catch-boundary";
import { NotFound } from "@qino-lingo/ui/components/not-found";

import { routeTree } from "./routeTree.gen";

export function getRouter() {
  const router = createRouter({
    routeTree,
    defaultPreload: "intent",
    defaultErrorComponent: DefaultCatchBoundary,
    defaultNotFoundComponent: () => <NotFound />,
    scrollRestoration: true,
  });

  return router;
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof getRouter>;
  }
}
