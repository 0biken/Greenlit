import * as RDialog from '@radix-ui/react-dialog'
import * as RMenu from '@radix-ui/react-dropdown-menu'
import * as RTooltip from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

// Thin wrappers over Radix so every overlay shares one motion and one look.
// Motion lives in components.css: popovers grow from their trigger, dialogs stay centred.

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  width = 520,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  children: ReactNode
  width?: number
}) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="dialog-overlay" />
        <RDialog.Content className="dialog" style={{ maxWidth: width }}>
          <RDialog.Title className="dialog-title">{title}</RDialog.Title>
          {description ? (
            <RDialog.Description className="dialog-desc">{description}</RDialog.Description>
          ) : (
            <RDialog.Description className="sr-only">{title}</RDialog.Description>
          )}
          {children}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

export const DialogClose = RDialog.Close

export function Menu({
  trigger,
  children,
  align = 'end',
}: {
  trigger: ReactNode
  children: ReactNode
  align?: 'start' | 'end'
}) {
  return (
    <RMenu.Root>
      <RMenu.Trigger asChild>{trigger}</RMenu.Trigger>
      <RMenu.Portal>
        <RMenu.Content className="menu" align={align} sideOffset={6} collisionPadding={12}>
          {children}
        </RMenu.Content>
      </RMenu.Portal>
    </RMenu.Root>
  )
}

export function MenuItem({ children, onSelect }: { children: ReactNode; onSelect?: () => void }) {
  return (
    <RMenu.Item className="menu-item" onSelect={onSelect}>
      {children}
    </RMenu.Item>
  )
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <RMenu.Label className="menu-label">{children}</RMenu.Label>
}

export const MenuSeparator = () => <RMenu.Separator className="menu-sep" />

export function TooltipProvider({ children }: { children: ReactNode }) {
  // First tooltip waits; neighbours open at once (skipDelayDuration).
  return (
    <RTooltip.Provider delayDuration={500} skipDelayDuration={400}>
      {children}
    </RTooltip.Provider>
  )
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <RTooltip.Root>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content className="tooltip" sideOffset={6}>
          {content}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  )
}
