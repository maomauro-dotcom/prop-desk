import * as React from "react";

type Variant = "default" | "outline" | "ghost" | "danger";

const styles: Record<Variant, string> = {
  default: "bg-accent text-white hover:bg-accent/90",
  outline: "border border-line bg-surface-2 text-ink-1 hover:bg-surface-3",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink-1",
  danger: "bg-bad/90 text-white hover:bg-bad",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = "", variant = "default", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={`inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:pointer-events-none
        disabled:opacity-50 ${size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm"} ${styles[variant]} ${className}`}
      {...props}
    />
  ),
);
Button.displayName = "Button";
