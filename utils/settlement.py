# -----------------------------
# CALCULATE TOTALS
# -----------------------------

def calculate_totals(sessions):

    totals = {}

    for session in sessions:

        for player in session["players"]:

            name = player["name"]

            result = float(
                player["result"]
            )

            totals[name] = (
                totals.get(name, 0)
                + result
            )

    return totals

# -----------------------------
# CALCULATE SETTLEMENTS
# -----------------------------

def calculate_settlements(totals):

    creditors = []
    debtors = []

    for player, amount in totals.items():

        if amount > 0:

            creditors.append([
                player,
                amount
            ])

        elif amount < 0:

            debtors.append([
                player,
                abs(amount)
            ])

    settlements = []

    i = 0
    j = 0

    while (
        i < len(debtors)
        and
        j < len(creditors)
    ):

        debtor = debtors[i]

        creditor = creditors[j]

        payment = min(
            debtor[1],
            creditor[1]
        )

        settlements.append({

            "from":
                debtor[0],

            "to":
                creditor[0],

            "amount":
                round(payment, 2)

        })

        debtor[1] -= payment
        creditor[1] -= payment

        if debtor[1] == 0:
            i += 1

        if creditor[1] == 0:
            j += 1

    return settlements