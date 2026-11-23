import { Check, ChevronDown } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import './CustomSelect.css';

export interface CustomSelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

export interface CustomSelectProps {
  value: string;
  options: CustomSelectOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  label?: string;
  disabled?: boolean;
  title?: string;
  variant?: 'topbar' | 'field';
  className?: string;
}

export function CustomSelect({
  value,
  options,
  onChange,
  ariaLabel,
  label,
  disabled = false,
  title,
  variant = 'field',
  className = '',
}: CustomSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuId = useId();
  const selected = options.find((option) => option.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={`aura-menu-select aura-menu-select--${variant} ${className} ${open ? 'is-open' : ''}`}>
      <button
        ref={triggerRef}
        type="button"
        className="aura-menu-select__trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-controls={menuId}
        aria-expanded={open}
        disabled={disabled}
        title={title}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {label ? <span className="aura-menu-select__caption">{label}</span> : null}
        <strong>{selected?.label ?? value || 'Choose…'}</strong>
        <ChevronDown className="aura-menu-select__chevron" size={13} aria-hidden="true" />
      </button>

      {open ? (
        <div id={menuId} className="aura-menu-select__menu" role="listbox" aria-label={ariaLabel}>
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={`aura-menu-select__option ${isSelected ? 'is-selected' : ''}`}
                disabled={option.disabled}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                  triggerRef.current?.focus();
                }}
              >
                <span className="aura-menu-select__option-copy">
                  <strong>{option.label}</strong>
                  {option.description ? <small>{option.description}</small> : null}
                </span>
                <span className="aura-menu-select__check" aria-hidden="true">
                  {isSelected ? <Check size={14} /> : null}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
