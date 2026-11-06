/** One vector asset for staff, client portal, sign-in and browser icons. */
export function BrandMark({className = ''}: {className?: string}) {
  return <img className={`brand-mark ${className}`.trim()} src="/brand-mark.svg" width={40} height={40} alt="" aria-hidden="true" draggable={false}/>;
}
