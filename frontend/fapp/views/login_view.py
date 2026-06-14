import tkinter as tk
from tkinter import ttk
from fapp.api_client import api, APIError


class LoginView(tk.Frame):
    def __init__(self, master, on_success):
        super().__init__(master, bg="white")
        self.on_success = on_success
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        header = tk.Frame(self, bg="#E8500A", height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.pack_propagate(False)
        tk.Label(header, text="Tiger Fitness Gym",
                 bg="#E8500A", fg="white",
                 font=("", 14, "bold")).pack(expand=True)

        tk.Label(self, text="Sign in to continue",
                 font=("", 10), fg="gray",
                 bg="white").grid(row=1, column=0, pady=(28, 4))

        form = tk.Frame(self, bg="white", padx=30, pady=20,
                        relief="groove", bd=1)
        form.grid(row=2, column=0, ipadx=20)

        tk.Label(form, text="Username", bg="white",
                 anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        self._user = tk.Entry(form, width=28)
        self._user.grid(row=1, column=0, pady=(0, 12))
        self._user.focus()

        tk.Label(form, text="Password", bg="white",
                 anchor="w").grid(row=2, column=0, sticky="w", pady=4)
        self._pass = tk.Entry(form, show="*", width=28)
        self._pass.grid(row=3, column=0, pady=(0, 16))
        self._pass.bind("<Return>", lambda _: self._login())

        tk.Button(form, text="Sign In", command=self._login,
                  bg="#E8500A", fg="white", relief="flat",
                  padx=16, pady=8, width=22).grid(row=4, column=0)

        self._status = tk.Label(self, text="", fg="red",
                                bg="white", font=("", 9))
        self._status.grid(row=3, column=0, pady=10)

    def _login(self):
        u = self._user.get().strip()
        p = self._pass.get().strip()
        if not u or not p:
            self._status.config(text="Username and password required.")
            return
        try:
            api.login(u, p)
            self.on_success()
        except APIError as e:
            self._status.config(text=str(e))
        except Exception:
            self._status.config(
                text="Cannot connect to server. Is the backend running?")