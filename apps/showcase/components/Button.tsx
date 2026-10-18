import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from './cx.ts'
import { Icon, type IconName } from './Icon.tsx'
import { SmartLink, isExternalHref } from './Link.tsx'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'btn-primary',
  secondary: 'btn',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
}
const SIZE: Record<ButtonSize, string> = { sm: 'btn-sm', md: '', lg: 'btn-lg' }

type Common = {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: IconName
  trailingIcon?: IconName
  className?: string
  children: ReactNode
}

const classes = ({ variant = 'secondary', size = 'md', className }: Pick<Common, 'variant' | 'size' | 'className'>) =>
  cx(VARIANT[variant], SIZE[size], className)

export function Button({
  variant, size, icon, trailingIcon, className, children, type = 'button', ...rest
}: Common & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className' | 'children'>) {
  return (
    <button type={type} className={classes({ variant, size, className })} {...rest}>
      {icon && <Icon name={icon} className="h-3.5 w-3.5" />}
      {children}
      {trailingIcon && <Icon name={trailingIcon} className="h-3.5 w-3.5" />}
    </button>
  )
}

/** A link that looks like a button (call-to-action, "Open in the Lab"). External links get the external glyph. */
export function ButtonLink({
  href, variant, size, icon, trailingIcon, className, children,
}: Common & { href: string }) {
  const trailing = trailingIcon ?? (isExternalHref(href) ? 'external' : undefined)
  return (
    <SmartLink href={href} className={classes({ variant, size, className })}>
      {icon && <Icon name={icon} className="h-3.5 w-3.5" />}
      {children}
      {trailing && <Icon name={trailing} className="h-3.5 w-3.5" />}
    </SmartLink>
  )
}
