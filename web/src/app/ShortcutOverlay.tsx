import * as RDialog from '@radix-ui/react-dialog'

// The `?` overlay. It opens and closes instantly: it is summoned from the keyboard.
const GROUPS: { title: string; keys: [string, string][] }[] = [
  {
    title: 'Anywhere',
    keys: [
      ['?', 'Show shortcuts'],
      ['g i', 'Go to Inbox'],
      ['g p', 'Go to Projects'],
      ['g s', 'Go to Settings'],
    ],
  },
  {
    title: 'Inbox',
    keys: [
      ['j / k', 'Next and previous item'],
      ['Enter', 'Open the item'],
      ['a', 'Take the next action'],
      ['s', 'Snooze with a reason'],
    ],
  },
  {
    title: 'Test runs',
    keys: [
      ['p', 'Passed'],
      ['f', 'Failed'],
      ['b', 'Blocked'],
      ['n', 'Not run'],
      ['e', 'Attach evidence'],
    ],
  },
  {
    title: 'Draft review',
    keys: [
      ['a', 'Accept'],
      ['r', 'Reject'],
      ['Enter', 'Edit'],
      ['j / k', 'Next and previous draft'],
    ],
  },
]

export function ShortcutOverlay({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="dialog-overlay instant" />
        <RDialog.Content className="dialog shortcuts instant" style={{ maxWidth: 720 }}>
          <RDialog.Title className="dialog-title">Keyboard shortcuts</RDialog.Title>
          <RDialog.Description className="dialog-desc">Shortcuts work when you are not typing in a field.</RDialog.Description>
          <div className="shortcut-grid">
            {GROUPS.map((g) => (
              <section key={g.title}>
                <h2 className="overline">{g.title}</h2>
                <dl>
                  {g.keys.map(([k, label]) => (
                    <div key={k + label} className="shortcut-row">
                      <dt>
                        {k.split(' ').map((part, i) =>
                          part === '/' ? (
                            <span key={i} className="faint">
                              {' '}
                              /{' '}
                            </span>
                          ) : (
                            <kbd key={i}>{part}</kbd>
                          ),
                        )}
                      </dt>
                      <dd>{label}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}
