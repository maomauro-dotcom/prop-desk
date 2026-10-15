import * as React from "react";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className = "", ...props }, ref) => (
    <input
      ref={ref}
      className={`h-8 w-full rounded-md border border-line bg-surface-0 px-2 text-sm text-ink-1 num
        placeholder:text-ink-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
        disabled:opacity-60 ${className}`}
      {...props}
    />
  ),
);
Input.displayName = "Input";
