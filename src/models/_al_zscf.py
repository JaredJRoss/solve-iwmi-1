"""
This is still provisional code. Just testing an idea.
"""

import numpy as np
from sklearn.base import ClassifierMixin, BaseEstimator, clone
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelEncoder
from transformers import pipeline


def _entropy_selection(probabs, leftover_ids, increment):
    e = (-probabs * np.log2(probabs)).sum(axis=1)
    new_ids = leftover_ids[np.argsort(e)[::-1][:increment]]
    return new_ids


def _margin_sampling_selection(probabs, leftover_ids, increment):
    """
    Selecting samples as a smallest difference of probability values
    between the first and second most likely classes
    """
    probs_sorted = np.sort(probabs, axis=1)[:, ::-1]
    values = probs_sorted[:, 0] - probs_sorted[:, 1]
    new_ids = leftover_ids[np.argsort(values)[:increment]]
    return new_ids


def _random_selection(leftover_ids, increment, rng):
    """
    Random sample selection. Random State object is required.
    """
    new_ids = rng.choice(leftover_ids, increment, replace=False)
    return new_ids


def data_selection(probabs, leftover_ids, increment, rng, selection_strategy):
    if selection_strategy == 'entropy':
        return _entropy_selection(probabs, leftover_ids, increment)
    elif selection_strategy == 'margin sampling':
        return _margin_sampling_selection(probabs, leftover_ids, increment)
    elif selection_strategy == 'random':
        return _random_selection(leftover_ids, increment, rng)
    else:
        msg = f"Selection strategy {selection_strategy} is \
        not implemented. Possible values are \
        ['entropy', 'margin sampling', 'random']."
        raise ValueError(msg)


class ALZeroShotWrapper(ClassifierMixin, BaseEstimator):
    def __init__(
        self,
        classifier,
        max_iter=1000,
        split_method=None,
        selection_strategy='entropy',
        n_initial=100,
        increment=50,
        save_classifiers=False,
        auto_load=True,
        evaluation_metric=None,
        random_state=None
    ):
        self.classifier = classifier
        self.max_iter = max_iter
        self.split_method = split_method
        self.selection_strategy = selection_strategy
        self.n_initial = n_initial
        self.increment = increment
        self.random_state = random_state

        # For finding the optimal classifier purposes
        self.auto_load = auto_load
        self.save_classifiers = save_classifiers
        self.evaluation_metric = evaluation_metric

    def fit(self, X, sequences, candidate_labels):

        if self.evaluation_metric is None:
            self.evaluation_metric_ = accuracy_score
        else:
            self.evaluation_metric_ = self.evaluation_metric

        if self.save_classifiers:
            self.classifiers_ = []

        if self.auto_load:
            self.classifier_ = None

        iter_n = 0
        rng = np.random.RandomState(self.random_state)
        selection = np.zeros(shape=(X.shape[0])).astype(bool)

        self.zscf = pipeline("zero-shot-classification")
        self.y = np.ones(X.shape[0]) * np.nan
        self.label_encoder = LabelEncoder().fit(candidate_labels)

        while iter_n < self.max_iter:
            print(f'iter {iter_n}') # it's here for debugging purposes
            classifier = clone(self.classifier)

            # add new samples to dataset
            leftover_ids = np.argwhere(~selection).squeeze()
            ids = (
                data_selection(
                    probabs,
                    leftover_ids,
                    self.increment,
                    rng,
                    self.selection_strategy
                )
                if iter_n != 0
                else
                rng.choice(leftover_ids, self.n_initial, replace=False)
            )
            selection[ids] = True

            # Assign ground truth labels based on zero-shot classification
            self.y[ids] = [
                self.zscf(sequences[i], candidate_labels)['labels'][0]
                for i in ids
            ]

            # train classifier and get probabilities
            classifier.fit(
                X[selection],
                self.label_encoder.transform(self.y[selection])
            )

            # save classifier
            if self.save_classifiers:
                self.classifiers_.append((selection.sum(), classifier))

            # Replace top classifier
            if self.auto_load:
                self.classifier_ = classifier

            # keep track of iter_n
            if self.max_iter is not None:
                iter_n += 1

            # stop if all examples have been included
            if selection.all():
                break

            probabs = classifier.predict_proba(X[~selection])

            # some selection strategies don't deal well with 0. values
            probabs = np.where(probabs == 0., 1e-10, probabs)

        return self

    def load_best_classifier(self, X, y):
        scores = []
        for _, classifier in self.classifiers_:
            y_pred = classifier.predict(X)
            scores.append(self.evaluation_metric_(y, y_pred))

        self.classifier_ = self.classifiers_[np.argmax(scores)][-1]
        return self

    def predict(self, X):
        return self.classifier_.predict(X)
