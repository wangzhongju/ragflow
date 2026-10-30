#!/usr/bin/env bash
# Initialize only the application container's interactive host-matched account.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'env.sh must run as container root' >&2; exit 2; }
user_name=${DOCKER_USER:?DOCKER_USER is required}
uid=${DOCKER_USER_ID:?DOCKER_USER_ID is required}
group_name=${DOCKER_GRP:?DOCKER_GRP is required}
gid=${DOCKER_GRP_ID:?DOCKER_GRP_ID is required}
[[ $user_name =~ ^[a-z_][a-z0-9_-]*$ && $group_name =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 2
[[ $uid =~ ^[0-9]+$ && $gid =~ ^[0-9]+$ && $uid -gt 0 && $gid -gt 0 ]] || exit 2
for tool in sudo vim bash visudo; do command -v "$tool" >/dev/null; done

if getent group "$group_name" >/dev/null; then
  [[ $(getent group "$group_name" | cut -d: -f3) == "$gid" ]] || {
    echo "Group $group_name has a different GID" >&2; exit 1;
  }
elif getent group "$gid" >/dev/null; then
  old_group=$(getent group "$gid" | cut -d: -f1)
  [[ $gid -ge 1000 ]] || { echo 'Refusing to rename a system group' >&2; exit 1; }
  groupmod --new-name "$group_name" "$old_group"
else
  groupadd --gid "$gid" "$group_name"
fi

user_home="/home/$user_name"
if id "$user_name" >/dev/null 2>&1; then
  [[ $(id -u "$user_name") == "$uid" && $(id -g "$user_name") == "$gid" ]] || {
    echo "User $user_name has a different UID/GID" >&2; exit 1;
  }
elif getent passwd "$uid" >/dev/null; then
  old_user=$(getent passwd "$uid" | cut -d: -f1)
  [[ $uid -ge 1000 ]] || { echo 'Refusing to rename a system user' >&2; exit 1; }
  usermod --login "$user_name" --home "$user_home" --shell /bin/bash --gid "$gid" "$old_user"
else
  useradd --uid "$uid" --gid "$gid" --home-dir "$user_home" --shell /bin/bash "$user_name"
fi
install -d -m 0750 -o "$uid" -g "$gid" "$user_home"
usermod -aG sudo "$user_name"
printf '%s ALL=(ALL:ALL) NOPASSWD:ALL\n' "$user_name" > /etc/sudoers.d/ragflow-developer
chmod 0440 /etc/sudoers.d/ragflow-developer
visudo -cf /etc/sudoers.d/ragflow-developer >/dev/null

# Personal configuration is created once. Ubuntu's standard .bashrc supplies
# history, aliases and bash-completion. The initial PS1 matches vision-pipeline;
# later user edits are left intact.
if [[ ! -e $user_home/.ragflow_env ]]; then
  cat > "$user_home/.ragflow_env" <<'EOF'
case ":$PATH:" in
  *:/ragflow/.venv/bin:*) ;;
  *) export PATH="/ragflow/.venv/bin:$PATH" ;;
esac
export PYTHONPATH="${PYTHONPATH:-/ragflow}"
export NLTK_DATA="${NLTK_DATA:-/usr/local/share/nltk_data}"
export EDITOR="${EDITOR:-vim}"
export VISUAL="${VISUAL:-vim}"
export LANG="${LANG:-C.UTF-8}"
EOF
  chown "$uid:$gid" "$user_home/.ragflow_env"
fi
for file in .bashrc .profile; do
  if [[ ! -e $user_home/$file ]]; then
    cp "/etc/skel/$file" "$user_home/$file"
    printf '\n# RAGFlow environment; this file is yours to customize.\n[ -f "$HOME/.ragflow_env" ] && . "$HOME/.ragflow_env"\n' >> "$user_home/$file"
    if [[ $file == .bashrc ]]; then
      cat >> "$user_home/$file" <<'EOF'
PS1='\[\033[01;32m\]\u@\[\033[01;35m\]\h\[\033[00m\]:\[\033[01;36m\]\w\[\033[00m\]$ '
EOF
    fi
    chown "$uid:$gid" "$user_home/$file"
  fi
done
if [[ ! -f $user_home/.vimrc ]]; then
  printf 'set encoding=utf-8\nset fileencodings=utf-8\nset number\nset expandtab\nset tabstop=4\nset shiftwidth=4\nsyntax on\n' > "$user_home/.vimrc"
  chown "$uid:$gid" "$user_home/.vimrc"
fi
echo "Application shell user ready: $user_name ($uid:$gid)"
