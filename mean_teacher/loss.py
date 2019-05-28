import tensorflow as tf
from .framework import assert_shape

def errors(logits, labels, name=None):
    """Compute error mean and whether each unlabeled example is erroneous

    Assume unlabeled examples have label == -1.
    Compute the mean error over unlabeled examples.
    Mean error is NaN if there are no unlabeled examples.
    Note that unlabeled examples are treated differently in cost calculation.
    """
    with tf.name_scope(name, "errors") as scope:
        applicable = tf.not_equal(labels, -1)
        labels = tf.boolean_mask(labels, applicable)
        logits = tf.boolean_mask(logits, applicable)
        predictions = tf.argmax(logits, -1)
        labels = tf.cast(labels, tf.int64)
        per_sample = tf.to_float(tf.not_equal(predictions, labels))
        mean = tf.reduce_mean(per_sample, name=scope)
        return mean, per_sample


def classification_costs(logits, labels, name=None):
    """Compute classification cost mean and classification cost per sample

    Assume unlabeled examples have label == -1. For unlabeled examples, cost == 0.
    Compute the mean over all examples.
    Note that unlabeled examples are treated differently in error calculation.
    """
    with tf.name_scope(name, "classification_costs") as scope:
        applicable = tf.not_equal(labels, -1)

        # Change -1s to zeros to make cross-entropy computable
        labels = tf.where(applicable, labels, tf.zeros_like(labels))

        # This will now have incorrect values for unlabeled examples
        per_sample = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=logits, labels=labels)

        # Retain costs only for labeled
        per_sample = tf.where(applicable, per_sample, tf.zeros_like(per_sample))

        # Take mean over all examples, not just labeled examples.
        labeled_sum = tf.reduce_sum(per_sample)
        total_count = tf.to_float(tf.shape(per_sample)[0])
        mean = tf.div(labeled_sum, total_count, name=scope)

        return mean, per_sample


def consistency_costs(logits1, logits2, cons_coefficient, mask, consistency_trust, name=None):
    """Takes a softmax of the logits and returns their distance as described below

    Consistency_trust determines the distance metric to use
    - trust=0: MSE
    - 0 < trust < 1: a scaled KL-divergence but both sides mixtured with
      a uniform distribution with given trust used as the mixture weight
    - trust=1: scaled KL-divergence

    When trust > 0, the cost is scaled to make the gradients
    the same size as MSE when trust -> 0. The scaling factor used is
    2 * (1 - 1/num_classes) / num_classes**2 / consistency_trust**2 .
    To have consistency match the strength of classification, use
    consistency coefficient = num_classes**2 / (1 - 1/num_classes) / 2
    which is 55.5555... when num_classes=10.

    Two potential stumbling blokcs:
    - When trust=0, this gives gradients to both logits, but when trust > 0
      this gives gradients only towards the first logit.
      So do not use trust > 0 with the Pi model.
    - Numerics may be unstable when 0 < trust < 1.
    """

    with tf.name_scope(name, "consistency_costs") as scope:
        num_classes = 10
        assert_shape(logits1, [None, num_classes])
        assert_shape(logits2, [None, num_classes])
        assert_shape(cons_coefficient, [])
        softmax1 = tf.nn.softmax(logits1)
        softmax2 = tf.nn.softmax(logits2)

        # kl_cost_multiplier = 2 * (1 - 1/num_classes) / num_classes**2 / consistency_trust**2

        def pure_mse():
            costs = tf.reduce_mean((softmax1 - softmax2) ** 2, -1)
            return costs

        # def pure_kl():
        #     cross_entropy = tf.nn.softmax_cross_entropy_with_logits(logits=logits1, labels=softmax2)
        #     entropy = tf.nn.softmax_cross_entropy_with_logits(logits=logits2, labels=softmax2)
        #     costs = cross_entropy - entropy
        #     costs = costs * kl_cost_multiplier
        #     return costs

        # def mixture_kl():
        #     with tf.control_dependencies([tf.assert_greater(consistency_trust, 0.0),
        #                                   tf.assert_less(consistency_trust, 1.0)]):
        #         uniform = tf.constant(1 / num_classes, shape=[num_classes])
        #         mixed_softmax1 = consistency_trust * softmax1 + (1 - consistency_trust) * uniform
        #         mixed_softmax2 = consistency_trust * softmax2 + (1 - consistency_trust) * uniform
        #         costs = tf.reduce_sum(mixed_softmax2 * tf.log(mixed_softmax2 / mixed_softmax1), axis=1)
        #         costs = costs * kl_cost_multiplier
        #         return costs

        costs = pure_mse()

        # costs = tf.case([
        #     (tf.equal(consistency_trust, 0.0), pure_mse),
        #     (tf.equal(consistency_trust, 1.0), pure_kl)
        # ], default=mixture_kl)

        costs = costs * tf.to_float(mask) * cons_coefficient
        mean_cost = tf.reduce_mean(costs, name=scope)
        assert_shape(costs, [None])
        assert_shape(mean_cost, [])
        return mean_cost, costs


def total_costs(*all_costs, name=None):
    with tf.name_scope(name, "total_costs") as scope:
        for cost in all_costs:
            assert_shape(cost, [None])
        costs = tf.reduce_sum(all_costs, axis=1)
        mean_cost = tf.reduce_mean(costs, name=scope)
        return mean_cost, costs

