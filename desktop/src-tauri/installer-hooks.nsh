!macro NSIS_HOOK_POSTINSTALL
  ; Keep the established AURA install directory, while giving Windows Search
  ; the user-facing Kuractus shortcut and display name. Rename Tauri's shortcut
  ; so its icon and shell properties stay intact.
  Delete "$SMPROGRAMS\Kuractus.lnk"
  Rename "$SMPROGRAMS\AURA.lnk" "$SMPROGRAMS\Kuractus.lnk"
  ; Tauri creates a desktop shortcut for silent installs. Preserve the user's
  ; choice on interactive installs and only rename one when it already exists.
  IfFileExists "$DESKTOP\AURA.lnk" 0 kuractus_skip_desktop_shortcut
  Delete "$DESKTOP\Kuractus.lnk"
  Rename "$DESKTOP\AURA.lnk" "$DESKTOP\Kuractus.lnk"
  kuractus_skip_desktop_shortcut:
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "Kuractus"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  Delete "$SMPROGRAMS\Kuractus.lnk"
  Delete "$DESKTOP\Kuractus.lnk"
!macroend
