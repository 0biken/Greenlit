import { forwardRef, type ButtonHTMLAttributes } from 'react'

// Ink is the default. Green ("go") is reserved for sign-off: the only green control in
// the product. Red outlines destructive actions. Labels start with a verb.
export type ButtonVariant = 'primary' | 'secondary' | 'go' | 'danger' | 'quiet'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: 'md' | 'sm'
}

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'secondary', size = 'md', className, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={['btn', `btn-${variant}`, size === 'sm' ? 'btn-sm' : '', className ?? ''].join(' ').trim()}
      {...rest}
    />
  )
})
