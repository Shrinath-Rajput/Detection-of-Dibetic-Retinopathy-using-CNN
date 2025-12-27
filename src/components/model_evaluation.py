class ModelEvaluation:
    def evaluate(self, model, val_gen):
        loss, accuracy = model.evaluate(val_gen)
        return accuracy
