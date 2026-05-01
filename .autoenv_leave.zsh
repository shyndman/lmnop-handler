if [[ -n "${VIRTUAL_ENV:-}" && "${VIRTUAL_ENV:A}" == "${varstash_dir}/.venv" ]] && typeset -f deactivate >/dev/null 2>&1; then
  deactivate
fi
