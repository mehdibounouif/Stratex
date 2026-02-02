# Quant_firm
# Getting Started

This guide will help you set up the project locally and understand how to work with the branch structure.

---

## Setup

Follow these steps carefully:

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd <repository-name>
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**

   * **Mac / Linux**

     ```bash
     source venv/bin/activate
     ```

   * **Windows**

     ```bash
     venv\Scripts\activate
     ```

4. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

5. **Environment variables**

   ```bash
   cp .env.example .env
   ```

   Open the `.env` file and add your API keys and required configuration values.

6. **Run the project**

   ```bash
   python main.py
   ```

---

## Branch Structure

The repository follows this branch organization:

```
main          # Production-ready code

development   # Testing and integration branch

data          # Abdilah's work

system        # Mehdi's work

risk          # Kawtar's work
```

### Branch Purpose

* **main**: Stable, production-ready code only.
* **development**: Where features are tested and integrated before production.
* **data / system / risk**: Personal or domain-specific working branches.

---

## Branch Management (Git Workflow)

### Check current branch

```bash
git branch
```

### Switch to a branch

```bash
git checkout branch-name
```

Example:

```bash
git checkout development
```

### Create a new branch

```bash
git checkout -b new-branch-name
```

### Pull latest changes

Always pull before starting work:

```bash
git pull origin branch-name
```

Example:

```bash
git pull origin development
```

### Add and commit changes

```bash
git add .
git commit -m "Clear and meaningful commit message"
```

### Push changes to remote

```bash
git push origin branch-name
```

Example:

```bash
git push origin system
```

### Merge into development (recommended flow)

1. Switch to development:

   ```bash
   git checkout development
   ```
2. Pull latest updates:

   ```bash
   git pull origin development
   ```
3. Merge your branch:

   ```bash
   git merge your-branch-name
   ```

⚠️ **Do not push directly to `main`** unless explicitly approved.

---

## Best Practices

* Pull before you code
* Commit small, logical changes
* Write clear commit messages
* Test before merging
* Keep `main` clean and stable

---

Happy coding 🚀
