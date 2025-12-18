class BudgetFSM:
    def __init__(self, budget, total_expense):
        self.budget = budget
        self.total_expense = total_expense

    def get_state(self):
        if self.total_expense < 0.8 * self.budget:
            return 'S3'  # Underspend/Saving More
        elif self.total_expense <= self.budget:
            return 'S0'  # On Track
        elif self.total_expense <= 1.05 * self.budget:
            return 'S1'  # Slight Overspend
        else:
            return 'S2'  # Major Overspend

    def get_pet_emotion(self):
        mapping = {
            # On track
            'S0': ('😊', 'neutral-car.gif'),
            # Slight overspend
            'S1': ('😟', 'slight_overspend.gif'),
            # Major overspend
            'S2': ('😢', 'major_overspend.gif'),
            # Underspend / saving more
            'S3': ('😺', 'happy-happy-happy-cat.gif'),
        }
        state = self.get_state()
        return mapping[state]
