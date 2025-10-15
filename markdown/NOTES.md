# Version Release Workflow (Authoritative Local Copy)

This project uses the local `main` branch as the **source of truth**.  
When creating a new version, follow this process to update the repository and push to the remote.

---

## 1. Commit All Local Changes

```bash
git status
if there are changes:
git add .
git commit -m "feat: <short description of changes>"

## 2. Update CHANGELOG.md
- Move items from [Unreleased] into a new version section with today’s date.
- Save and commit:
git add CHANGELOG.md
git commit -m "docs: update changelog for vX.Y.Z"

## 3. Create Annotated Tag
git tag -a vX.Y.Z -m "Release vX.Y.Z: <short summary from changelog>"

## 4. Push Local Main to Remote (Overwrite Remote)
git push origin main --force

## 5. Push the New Tag
git push origin vX.Y.Z

## Example for v2.2.2
git add .
git commit -m "feat: implement job title extraction improvements"
git add CHANGELOG.md
git commit -m "docs: update changelog for v2.2.2"
git tag -a v2.2.2 -m "Release v2.2.2: job title extraction improvements"
git push origin main --force
git push origin v2.2.2