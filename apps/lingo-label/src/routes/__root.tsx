/**
 * Root Layout Component - qino-label
 *
 * Keyboard-driven labeling interface for conversation analysis.
 * No authentication, no tRPC backend - uses server functions for corpus.db access.
 */

import * as React from "react";
import {
  createRootRoute,
  HeadContent,
  Link,
  Outlet,
  Scripts,
} from "@tanstack/react-router";
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools";

import { DefaultCatchBoundary } from "~/ui/components/default-catch-boundary";
import { NotFound } from "~/ui/components/not-found";

import appCss from "../app.css?url";

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "qino-label" },
    ],
    links: [
      { rel: "stylesheet", href: appCss },
      {
        rel: "apple-touch-icon",
        sizes: "180x180",
        href: "/apple-touch-icon.png",
      },
      {
        rel: "icon",
        type: "image/png",
        sizes: "32x32",
        href: "/favicon-32x32.png",
      },
      {
        rel: "icon",
        type: "image/png",
        sizes: "16x16",
        href: "/favicon-16x16.png",
      },
      { rel: "manifest", href: "/site.webmanifest" },
      { rel: "icon", href: "/favicon.ico" },
    ],
  }),
  errorComponent: (props) => (
    <RootDocument>
      <DefaultCatchBoundary {...props} />
    </RootDocument>
  ),
  notFoundComponent: () => <NotFound />,
  component: RootComponent,
});

function RootComponent() {
  return (
    <RootDocument>
      <Outlet />
    </RootDocument>
  );
}

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <HeadContent />
      </head>
      <body className="antialiased bg-neutral-950 text-neutral-100">
        <header className="sticky top-0 z-20 w-full border-b border-neutral-800 bg-neutral-900/95 shadow-sm backdrop-blur-sm">
          <div className="mx-auto flex h-(--header-height) max-w-6xl items-center justify-between px-4">
            <Link
              to="/"
              className="text-lg tracking-tight text-neutral-100 transition hover:text-neutral-300"
            >
              qino-label
            </Link>
            <nav className="flex items-center gap-4 text-sm text-neutral-400">
              <span>j/k navigate • 1-5 rate • Enter submit</span>
            </nav>
          </div>
        </header>

        <main className="h-[calc(100vh-var(--header-height))]">{children}</main>

        <TanStackRouterDevtools position="bottom-right" />

        <Scripts />
      </body>
    </html>
  );
}
